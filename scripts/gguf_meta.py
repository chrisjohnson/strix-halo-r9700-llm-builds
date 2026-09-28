import struct, sys
def rs(f):
    n=struct.unpack('<Q',f.read(8))[0]; return f.read(n).decode('utf-8','replace')
S={0:('B',1),1:('b',1),2:('<H',2),3:('<h',2),4:('<I',4),5:('<i',4),6:('<f',4),7:('?',1),10:('<Q',8),11:('<q',8),12:('<d',8)}
A=S
def rv(f,t):
    if t==8: return rs(f)
    if t==9:
        et=struct.unpack('<I',f.read(4))[0]; n=struct.unpack('<Q',f.read(8))[0]
        if et==8: return [rs(f) for _ in range(n)]
        fmt,sz=A[et]; return list(struct.unpack('<%d%s'%(n,fmt.lstrip('<')),f.read(n*sz)))
    fmt,sz=S[t]; return struct.unpack(fmt,f.read(sz))[0]
p=sys.argv[1]
with open(p,'rb') as f:
    assert f.read(4)==b'GGUF'
    ver=struct.unpack('<I',f.read(4))[0]; nt=struct.unpack('<Q',f.read(8))[0]; nk=struct.unpack('<Q',f.read(8))[0]
    print(f"# {p.split('/')[-1]}  gguf v{ver} tensors={nt} kv={nk}")
    for _ in range(nk):
        k=rs(f); t=struct.unpack('<I',f.read(4))[0]; v=rv(f,t)
        if isinstance(v,list) and len(v)>12:
            print(f"{k} = n={len(v)} uniq={sorted(set(map(str,v)))[:8]}")
        else: print(f"{k} = {v}")
