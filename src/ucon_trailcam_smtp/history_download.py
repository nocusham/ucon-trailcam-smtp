"""Explicit private historical exports, separate from automatic queue state."""
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from ucon_trailcam_smtp.cloud_image import validate_image
from ucon_trailcam_smtp.event_match import match_events
from ucon_trailcam_smtp.service_download import validate_batch_limit, WINDOW_SECONDS

MAX_BYTES = 16 * 1024 * 1024


def one(db, table, columns, uid, ident):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return None
    return db.execute(f'SELECT {columns} FROM {table} WHERE camera_uid=? AND itemid=?',
                      (uid,ident)).fetchone()


def read_original(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('Unsafe original path')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError('Unsafe original file')
        data = source.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise ValueError('Original exceeds size limit')
    ext,w,h = validate_image(data)
    if ext!='jpg':
        raise ValueError('Original is not JPEG')
    return data, (hashlib.sha256(data).hexdigest(),len(data),w,h)


def local_original(db, uid, ident, stamp, state):
    receipt = one(db,'downloads','sd_time,path,sha256,size,width,height',uid,ident)
    removed = one(db,'media_cleanup','removed_utc,size',uid,ident)
    if receipt is None:
        if removed is not None or state in ('downloaded','sent'):
            raise ValueError('Missing original receipt')
        return None
    sd,raw,*details = receipt
    if type(sd) is not int or abs(sd-stamp)>2:
        raise ValueError('Original receipt timestamp mismatch')
    path = Path(raw)
    if removed is not None:
        if removed[0]<=0 or removed[1]!=details[1] or path.exists() or path.is_symlink():
            raise ValueError('Unfinished or inconsistent original cleanup')
        return None
    data,actual = read_original(path)
    if actual!=tuple(details):
        raise ValueError('Original failed receipt verification')
    return sd,path.name,data,actual


def new_export(parent):
    parent = Path(parent).absolute()
    parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if parent.resolve()!=parent or parent.stat().st_uid!=os.geteuid() or parent.stat().st_mode & 0o022:
        raise ValueError('Export parent must be owner-controlled and not a symlink')
    return Path(tempfile.mkdtemp(prefix='history-',dir=parent))


def event_folder(root,uid,ident):
    key = hashlib.sha256(json.dumps([uid,ident]).encode()).hexdigest()
    folder = root/key
    folder.mkdir(mode=0o700)
    return folder


def record_export(manifest,root,uid,ident,stamp,state,raw,sd,dest,details,source):
    digest,size,width,height = details
    metadata = json.loads(raw)
    if not isinstance(metadata,dict) or metadata.get('itemid')!=ident or metadata.get('et_utc')!=stamp or metadata.get('type')!=1:
        raise ValueError('Invalid export metadata')
    record = {'camera_uid':uid,'itemid':ident,'et_utc':stamp,'prior_state':state,
              'metadata':metadata,'sd_time':sd,'file':dest.relative_to(root).as_posix(),
              'sha256':digest,'size':size,'width':width,'height':height,'source':source}
    manifest.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n')
    manifest.flush()


@contextmanager
def relay_batch(device, begin, end):
    from ucon_trailcam_smtp.camera_selection import relay_credentials
    from ucon_trailcam_smtp.sdk_relay import DiagnosticRelay, relay_compat
    from ucon_trailcam_smtp.h4_events import list_events_staged
    from ucon_trailcam_smtp.h4_download import download_photo
    uid,password,_ = relay_credentials(device)
    session = DiagnosticRelay(uid,password)
    session.started = time.monotonic()
    with relay_compat(session),session:
        events = list_events_staged(session,max(0,begin-6),end+6,flow='app')
        def fetch(event,dest):
            return download_photo(session,event,3,dest,preserve_filename=True,require_native_filename=True)
        yield events,fetch


def export_history(db,uid,local,remote,parent,limit,open_batch,*,emit=print):
    """Export independent copies; never write primary queue or receipt state."""
    validate_batch_limit(limit)
    root = new_export(parent)
    emit(f'Private history export created: {root}')
    exported = skipped = 0
    pending = []
    candidates = {}
    for ident in local.keys() | remote.keys():
        if ident in local:
            stamp,state = local[ident]
            raw, = db.execute('SELECT metadata_json FROM events WHERE camera_uid=? AND itemid=?',
                              (uid,ident)).fetchone()
        else:
            stamp,raw = remote[ident]
            state = 'unknown_history'
        meta = json.loads(raw)
        if (not isinstance(meta,dict) or meta.get('itemid')!=ident
                or type(meta.get('et_utc')) is not int or meta['et_utc']!=stamp
                or type(meta.get('type')) is not int or meta['type']!=1):
            raise ValueError('Invalid historical event metadata')
        candidates[ident] = (stamp,state,raw)
    claimed = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='downloads'").fetchone():
        claimed = dict(db.execute('SELECT sd_time,itemid FROM downloads WHERE camera_uid=?',(uid,)))
    fd = os.open(root/'manifest.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as manifest:
        for ident,(stamp,state,raw) in sorted(candidates.items(),key=lambda x:(x[1][0],x[0])):
            delivery = one(db,'deliveries','accepted_utc',uid,ident)
            if state=='uncertain' or (delivery is not None and delivery[0] is None):
                skipped += 1
                continue
            original = local_original(db,uid,ident,stamp,state)
            if original is None:
                pending.append((ident,stamp,state,raw))
                continue
            sd,name,data,details = original
            folder = event_folder(root,uid,ident)
            dest = folder/name
            fd = os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:
                out.write(data)
            record_export(manifest,root,uid,ident,stamp,state,raw,sd,dest,details,'local')
            exported += 1
        while pending:
            begin = pending[0][1]
            end = begin + WINDOW_SECONDS
            n = min(limit,sum(row[1]<end for row in pending))
            batch,pending = pending[:n],pending[n:]
            # Include all nearby known identities, including non-selected
            # neighbors, to reject ambiguous cloud-to-SD matching.
            neighbors = {ident:stamp for ident,(stamp,_,_) in candidates.items()
                         if begin-4<=stamp<end+4}
            for ident,stamp in db.execute('SELECT itemid,et_utc FROM events WHERE camera_uid=? '
                                          'AND et_utc>=? AND et_utc<?',(uid,begin-4,end+4)):
                neighbors[ident]=stamp
            identities = sorted(neighbors)
            with open_batch(begin,end) as (events,fetch):
                matches = dict(zip(identities,match_events([neighbors[i] for i in identities],events)))
                for ident,stamp,state,raw in batch:
                    _,status,sd = matches[ident]
                    if status!='matched' or (sd in claimed and claimed[sd]!=ident):
                        skipped += 1
                        continue
                    event, = [e for e in events if e.start_time==sd and e.event_type==4 and e.length==65535]
                    folder = event_folder(root,uid,ident)
                    dest = Path(fetch(event,folder/f'event4_{sd}_original.jpg'))
                    if (dest.parent!=folder or '..' in dest.name or not re.fullmatch(
                            r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?i:jpg|jpeg)',dest.name)):
                        raise ValueError('Unexpected historical download destination')
                    _,details = read_original(dest)
                    dest.chmod(0o600)
                    claimed[sd]=ident
                    record_export(manifest,root,uid,ident,stamp,state,raw,sd,dest,details,'sd')
                    exported += 1
            emit(f'History export: verified={exported}, skipped={skipped}, remaining={len(pending)}.')
    emit(f'History export complete: verified={exported}, skipped={skipped}; no SMTP or queue changes.')
    return int(bool(skipped))
