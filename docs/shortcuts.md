# Keyboard and mouse

- Menu items show their keys. The tables list every default binding, also of functions without a menu item.
- All keys but the two bookmark ones can be changed: see the last section.
- `KeyPad` is the numeric keypad: `KeyPadHome` is its Home key.
- `BackMouse` and `ForwardMouse` are the mouse's thumb buttons.

## Opening files and moving from page to page

Function | Binding
---------|--------
Open file | CTRL+O
Open library | CTRL+L
Close file | CTRL+W
Next page | PageDown, KeyPadPageDown, LeftMouse
Previous page | PageUp, KeyPadPageUp, Backspace, BackMouse, ALT+RightMouse
Page to the right | ALT+Right
Page to the left | ALT+Left
Forward ten pages | SHIFT+PageDown, SHIFT+KeyPadPageDown, SHIFT+LeftMouse
Back ten pages | SHIFT+PageUp, SHIFT+KeyPadPageUp, SHIFT+Backspace, SHIFT+RightMouse
Ten pages to the right | SHIFT+ALT+Right
Ten pages to the left | SHIFT+ALT+Left
Forward only one page (in double page mode) | CTRL+PageDown, CTRL+KeyPadPageDown
Go back only one page (in double page mode) | CTRL+PageUp, CTRL+KeyPadPageUp, CTRL+Backspace
One page to the right (in double page mode) | CTRL+Right, CTRL+KeyPadRight
One page to the left (in double page mode) | CTRL+Left, CTRL+KeyPadLeft
First page | Home, KeyPadHome
Last page | End, KeyPadEnd
Go to page | G
Next archive | CTRL+SHIFT+N
Previous archive | CTRL+SHIFT+P
Next directory | CTRL+N
Previous directory | CTRL+P

In manga mode the page to the right is the previous one, the page to the left the next. PageDown and PageUp always go forward and back.

## Reading and scrolling

Function | Binding
---------|--------
Scroll down | Down, KeyPadDown
Scroll up | Up, KeyPadUp
Scroll left | Left, KeyPadLeft, MouseWheelLeft
Scroll right | Right, KeyPadRight, MouseWheelRight
Scroll by dragging the page | LeftMouse
Smart scroll down | Space, MouseWheelDown
Smart scroll up | SHIFT+Space, MouseWheelUp
Inverse direction of smart scrolling | X
Align the page to a corner, an edge or the centre | KeyPad1 to KeyPad9, as the keys lie
Show magnifying lens | L, MiddleMouse
Show OSD panel | TAB, ForwardMouse

- The wheel scrolls smartly only with "Use smart scrolling" on; otherwise by a fixed number of pixels.
- Tilted, or swiped sideways on a touchpad, it scrolls across a wide page and turns it at the side, like the arrow keys.

## The view

Function | Binding
---------|--------
Toggle fullscreen mode | F, F11
Leave fullscreen mode | Escape
Toggle double page mode | D
Toggle manga mode | M
Toggle slideshow mode | CTRL+S
Best fit mode | B
Fit to width mode | W
Fit to height mode | H
Fixed size mode | S
Manual zoom mode | A
Stretch small images | Y
Zoom in | Plus, KeyPadAdd, Equal, CTRL+MouseWheelUp
Zoom out | Minus, KeyPadSubtract, CTRL+MouseWheelDown
Reset zoom | CTRL+0, KeyPad0
Rotate 90 degrees clockwise | R
Rotate 90 degrees anticlockwise | SHIFT+R
Keep transformation between pages | K
Invert image colours | CTRL+I
Show/hide menubar | CTRL+M
Show/hide thumbnails | F9
Hide/show all UI elements | I

To quit with Escape, give it to Quit in the editor below. While pages are picked out, Escape first puts them all back, whatever it is bound to.

## Other functions

Function | Binding
---------|--------
Preferences | F12
Archive comments | C
Properties | ALT+Return
Enhance image | E
Save currently opened image | CTRL+SHIFT+S
Reload currently opened directory or archive | CTRL+SHIFT+R
Pick a page out, or put it back | CTRL+LeftMouse
Mark a page to swap, or swap it with the marked one | CTRL+SHIFT+LeftMouse
Swap two pages side by side | CTRL+SHIFT+LeftMouse dragged onto the other page
Delete the page or the file | Delete
Delete the file permanently | SHIFT+Delete
Rename page | F2
Undo | CTRL+Z
Redo | CTRL+Y, CTRL+SHIFT+Z
Add bookmark | CTRL+D
Edit bookmarks | CTRL+B
Open the page's menu | RightMouse, Menu, SHIFT+F10
Minimize window | N
Quit program | CTRL+Q
Save and quit | CTRL+SHIFT+Q
Execute first, second, ... external command (see [External commands](external-commands.md)) | 1 to 9

- Delete removes the pages picked out with CTRL+LeftMouse; with none picked out, it asks before moving the file to the trash.
- SHIFT+Delete asks before deleting the file permanently, without the trash; pages picked out are removed as Delete removes them.
- Where the trash would refuse the file, Delete asks to delete it permanently instead. GLib keeps no trash on a folder bind-mounted from another partition, or on a tmpfs such as /tmp.
- No key until given one: Rotate 180°, Flip horizontally, Flip vertically, Never autorotate, the two rotations under "Autorotate by width" and the two under "Autorotate by height", Toolbar, Statusbar, Scrollbars and Edit archive.

## Changing keys

- The preferences' Shortcuts tab lists every function by group, with a column per key.
- Click a key and press the new combination. Backspace or Delete clears it; Escape keeps it.
- A combination belongs to one function only: giving it to one takes it off any other.
- The bindings live as JSON in `keybindings.conf`, in MComix' [settings folder](troubleshooting.md#settings-and-data). MComix rewrites it on every change and on quitting, so edit it by hand only while MComix is closed.
- A file MComix cannot read is renamed `keybindings.conf.broken`, and the default keys are used.
