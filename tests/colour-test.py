import time
from dabble import lcd_ui
import colorsys
from pypalettes import load_cmap, load_palette, create_cmap
import matplotlib.colors

def rgb_tuple_to_rgb_str(color:tuple)->str:
    return "rgb(" + ",".join([ str(c) for c in color]) + ")"

#colors=["#004b23","#006400","#007200","#008000","#38b000","#70e000","#9ef01a","#ccff33"]
#colors=["#2b2d42","#8d99ae","#edf2f4","#ef233c","#d90429","#FF0F37"]
colors=["#f2002b","#f64021","#f98016","#fcc00b","#ffff00","#00cc66","#496ddb","#7209b7","#a01a7d"]
num_colours=len(colors)

print(f'Have {num_colours} colours')
ui=lcd_ui.LCDUI()

x_step=ui.WIDTH//num_colours-1
c=0

for x in range(0,ui.WIDTH,x_step):
    print(colors[c])
    rgb_c=matplotlib.colors.to_rgb(colors[c])
    hsv_c=matplotlib.colors.rgb_to_hsv(rgb_c)
    rgb_c=matplotlib.colors.hsv_to_rgb(hsv_c)
    rgb_c_hex=matplotlib.colors.to_hex(rgb_c)
    #ui.draw.rectangle((x,0,x+x_step,ui.HEIGHT), rgb_tuple_to_rgb_str(cmap[c]))
    #ui.draw.rectangle((x,0,x+x_step,ui.HEIGHT), colors[c])
    ui.draw.rectangle((x,0,x+x_step,ui.HEIGHT), rgb_c_hex)
    ui.update()
    c+=1


