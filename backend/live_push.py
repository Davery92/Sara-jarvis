import asyncio
from app.db.session import SessionLocal
from app.models.user import User
from app.models.background_task import BackgroundTask
from app.models.note import Note
from app.models.push_token import PushToken
from app.services import web_investigation

db = SessionLocal()
david = db.query(User).filter(User.email=="david@avery.cloud").first()
uid = david.id
ntok = db.query(PushToken).filter(PushToken.user_id==uid).count()
db.close()
print(f"david uid={uid} tokens={ntok}", flush=True)

async def go():
    db = SessionLocal()
    res = await web_investigation.dispatch_investigation(db, uid, ["https://example.com"])
    tid = res["task_id"]; db.close()
    print("dispatched:", tid, flush=True)
    for i in range(120):
        await asyncio.sleep(3)
        d = SessionLocal()
        t = d.query(BackgroundTask).filter(BackgroundTask.id==tid).first()
        st, nid = t.status, t.result_note_id
        d.close()
        if st in ("completed","failed"):
            if st=="completed" and not nid:
                await asyncio.sleep(6)
                d=SessionLocal(); nid=d.query(BackgroundTask).filter(BackgroundTask.id==tid).first().result_note_id; d.close()
            print(f"FINAL status={st} note_id={nid}", flush=True)
            return
    print("timed out", flush=True)
asyncio.run(go())
