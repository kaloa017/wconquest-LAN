"""Generate the public 1200x630 PNG social card using only Python's standard library."""
from pathlib import Path
import struct,zlib

FONT={
 'A':['01110','10001','10001','11111','10001','10001','10001'],
 'B':['11110','10001','10001','11110','10001','10001','11110'],
 'C':['01111','10000','10000','10000','10000','10000','01111'],
 'D':['11110','10001','10001','10001','10001','10001','11110'],
 'E':['11111','10000','10000','11110','10000','10000','11111'],
 'I':['11111','00100','00100','00100','00100','00100','11111'],
 'L':['10000','10000','10000','10000','10000','10000','11111'],
 'N':['10001','11001','11001','10101','10011','10011','10001'],
 'O':['01110','10001','10001','10001','10001','10001','01110'],
 'Q':['01110','10001','10001','10001','10101','10010','01101'],
 'R':['11110','10001','10001','11110','10100','10010','10001'],
 'S':['01111','10000','10000','01110','00001','00001','11110'],
 'T':['11111','00100','00100','00100','00100','00100','00100'],
 'U':['10001','10001','10001','10001','10001','10001','01110'],
 'W':['10001','10001','10001','10101','10101','10101','01010']}


def build():
    width,height=1200,630;pixels=bytearray(bytes((13,22,34))*(width*height))
    def rect(x,y,w,h,color):
        for row in range(max(0,y),min(height,y+h)):
            a=(row*width+max(0,x))*3;b=(row*width+min(width,x+w))*3;pixels[a:b]=bytes(color)*((b-a)//3)
    for row in range(11):
        for col in range(22):
            if (row*7+col*13)%11<7:
                rect(col*58-30,row*58-20,55,55,[(22,49,57),(29,61,66),(39,54,74)][(row+col)%3])
    rect(80,178,1040,280,(13,22,34));rect(80,178,1040,5,(229,187,114))
    def text(value,y,scale,color):
        x=(width-(len(value)*6-1)*scale)//2
        for letter in value:
            for row,bits in enumerate(FONT.get(letter,['00000']*7)):
                for col,bit in enumerate(bits):
                    if bit=='1':rect(x+col*scale,y+row*scale,scale,scale,color)
            x+=6*scale
    text('WORLD CONQUEST',230,11,(255,218,160));text('BUILD TRADE CONQUER',365,4,(193,203,218))
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    raw=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,9))+chunk(b'IEND',b'')
    (Path(__file__).resolve().parents[1]/'static'/'share-card.png').write_bytes(png)


if __name__=='__main__':build()
