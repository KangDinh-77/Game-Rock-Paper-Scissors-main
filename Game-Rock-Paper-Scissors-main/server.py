import asyncio
import json
import websockets
from collections import defaultdict

PORT = 8765

clients = dict()       # websocket -> player_name
queue = []             # websocket đang chờ đối thủ
rooms = []             # list of set(ws1, ws2)
choices = dict()       # websocket -> choice

# Gửi message tới tất cả client
async def notify_all(message):
    if clients:
        data = json.dumps(message)
        await asyncio.gather(*[ws.send(data) for ws in clients.keys()], return_exceptions=True)

# Gửi message tới 1 client
async def send_to(ws, message):
    try:
        await ws.send(json.dumps(message))
    except Exception:
        pass

# Quyết định kết quả vòng
def decide_round(choices_map):
    rev = defaultdict(list)
    for ws, ch in choices_map.items():
        rev[ch].append(ws)

    all_choices = set(rev.keys())
    results = {}

    if len(choices_map) <= 1 or len(all_choices) == 1:
        for ws in choices_map:
            results[ws] = 'draw'
        return results

    beats = {'rock': 'scissors', 'scissors': 'paper', 'paper': 'rock'}

    if len(all_choices) == 3:
        for ws in choices_map:
            results[ws] = 'draw'
        return results

    winners_choices = set()
    for ch in all_choices:
        for other in all_choices:
            if beats[ch] == other:
                winners_choices.add(ch)

    for ws, ch in choices_map.items():
        results[ws] = 'win' if ch in winners_choices else 'lose'
    return results

# Tìm phòng của người chơi
def find_room(ws):
    for room in rooms:
        if ws in room:
            return room
    return None

async def handler(ws):
    try:
        async for message in ws:
            try:
                msg = json.loads(message)
            except Exception:
                continue

            t = msg.get('type')

            # Join
            if t == 'join':
                name = msg.get('name') or 'Anon'
                clients[ws] = name
                await send_to(ws, {'type':'system','text':'Chào bạn! Đang tìm đối thủ...'})
                # Ghép phòng
                if queue:
                    opponent = queue.pop(0)
                    room = {ws, opponent}
                    rooms.append(room)
                    await asyncio.gather(
                        send_to(ws, {'type':'system','text':f"Đã ghép với {clients[opponent]}! Bắt đầu chơi!"}),
                        send_to(opponent, {'type':'system','text':f"Đã ghép với {clients[ws]}! Bắt đầu chơi!"})
                    )
                else:
                    queue.append(ws)

            # Choice
            elif t == 'choice':
                choice = msg.get('choice')
                if choice not in ('rock','paper','scissors'):
                    await send_to(ws, {'type':'error','text':'Lựa chọn không hợp lệ'})
                    continue
                room = find_room(ws)
                if not room:
                    await send_to(ws, {'type':'system','text':'Bạn chưa có đối thủ, đang chờ...'})
                    continue

                choices[ws] = choice
                await asyncio.gather(*[send_to(p, {'type':'system','text':f"{clients[ws]} đã chọn xong"}) for p in room])

                if all(p in choices for p in room):
                    res = decide_round({p: choices[p] for p in room})
                    payload = {'type':'round_result','results':[]}
                    for pws in room:
                        payload['results'].append({
                            'name': clients.get(pws,'Anon'),
                            'choice': choices[pws],
                            'result': res[pws]
                        })
                    await asyncio.gather(*[send_to(p, payload) for p in room])
                    for pws in room:
                        choices.pop(pws)

            # Chat
            elif t == 'chat':
                text = msg.get('text','')
                room = find_room(ws)
                if room:
                    await asyncio.gather(*[send_to(p, {'type':'chat','from':clients.get(ws,'Anon'),'text':text}) for p in room])
                else:
                    await send_to(ws, {'type':'chat','from':'System','text':'Chưa có đối thủ, không thể chat.'})

    except websockets.ConnectionClosed:
        pass
    finally:
        name = clients.pop(ws, None)
        # Xóa khỏi queue
        if ws in queue:
            queue.remove(ws)
        # Xóa khỏi phòng
        room = find_room(ws)
        if room:
            rooms.remove(room)
            other = next(iter(room - {ws}), None)
            if other:
                await send_to(other, {'type':'system','text':'Đối thủ đã rời. Bạn trở lại hàng chờ.'})
                queue.append(other)
        # Xóa lựa chọn
        choices.pop(ws, None)

async def main():
    async with websockets.serve(handler, '0.0.0.0', PORT):
        print(f"✅ Server started at ws://localhost:{PORT}")
        await asyncio.Future()  # run forever

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Server stopped')
