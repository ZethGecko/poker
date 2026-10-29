with open('server/app.py', 'r') as f:
    content = f.read()

# Replace all manager.get_room calls with manager.get
content = content.replace('manager.get_room(room_code)', 'manager.get(room_code)')

with open('server/app.py', 'w') as f:
    f.write(content)

print('Fixed all manager.get_room calls to manager.get')