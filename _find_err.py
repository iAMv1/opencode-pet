lines=open('ARCHITECTURE_MAP.html','r',encoding='utf-8').readlines()
for i in range(110,145):
    print(f'{i+1}: {lines[i].rstrip()}')
