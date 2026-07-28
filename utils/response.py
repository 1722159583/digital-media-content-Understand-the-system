import uuid

def success(data=None, msg="操作成功", code=200):
    payload = {
        "code": code,
        "msg": msg,
        "data": data or {},
        "traceId": uuid.uuid4().hex[:8]
    }
    return payload, code

def error(msg="操作失败", code=400):
    return {
        "code": code,
        "msg": msg,
        "data": {},
        "traceId": uuid.uuid4().hex[:8]
    }, code
