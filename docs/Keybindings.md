Keybindings
===

Menu items show their key beside their label. The tables below list every binding MComix starts with, including those of functions with no menu item. All keys except the two bookmark ones can be changed, as the last section describes.

Keys are written as a keyboard names them. `KeyPad` is the numeric keypad, so `KeyPadHome` is the Home key on the keypad. `BackMouse` and `ForwardMouse` are the thumb buttons a mouse marks "back" and "forward".

Opening files and moving from page to page
---

Function | Binding
---------|--------
Open file | CTRL+O
Open library | CTRL+L
Close file | CTRL+W
Next page | PageDown, KeyPadPageDown, LeftMouse
Previous page | PageUp, KeyPadPageUp, Backspace, BackMouse, ALT+RightMouse
Page to the right | ALT+Right
Page to the left | ALT+Left
Forward ten pages | SHIFT+PageDown, SHIFT+KeyPadPageDown, SHIFT+ALT+Right, SHIFT+LeftMouse
Back ten pages | SHIFT+PageUp, SHIFT+KeyPadPageUp, SHIFT+Backspace, SHIFT+ALT+Left, SHIFT+RightMouse
Forward only one page (in double page mode) | CTRL+PageDown, CTRL+KeyPadPageDown
Go back only one page (in double page mode) | CTRL+PageUp, CTRL+KeyPadPageUp, CTRL+Backspace
First page | Home, KeyPadHome
Last page | End, KeyPadEnd
Go to page | G
Next archive | SHIFT+CTRL+N
Previous archive | SHIFT+CTRL+P
Next directory | CTRL+N
Previous directory | CTRL+P

In manga mode the page to the right is the previous one, and the page to the left the next. PageDown and PageUp always go forward and back.

Reading and scrolling
---

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

The wheel scrolls smartly only while "Use smart scrolling" is on in the preferences, and by a fixed number of pixels otherwise. Tilted sideways, or swiped sideways on a touchpad, it scrolls across a page wider than the window and turns the page at the side, as the arrow keys do.

The view
---

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

Escape quits instead where "Escape key closes program" is on in the preferences.

Other functions
---

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
Rename page | F2
Undo | CTRL+Z
Redo | CTRL+Y, CTRL+SHIFT+Z
Add bookmark | CTRL+D
Edit bookmarks | CTRL+B
Open the page's menu | RightMouse, Menu, SHIFT+F10
Minimize window | N
Quit program | CTRL+Q
Save and quit | CTRL+SHIFT+Q
Execute first, second, ... external command (see [External Commands](External_Commands.md)) | 1 to 9

Delete takes the pages picked out with CTRL+LeftMouse out of the book; with none picked out, it asks before deleting the file from disk.

These functions have no key until one is given to them: Rotate 180°, Flip horizontally, Flip vertically, Never autorotate, the two rotations under "Autorotate by width" and the two under "Autorotate by height", Toolbar, Statusbar, Scrollbars and Edit archive.

Customizing hotkeys
---

The Shortcuts tab of the preferences dialog lists every function by group, with a column for each of its keys. Click a key and press the combination you want; Backspace or Delete clears it, and Escape leaves it as it was. A combination reaches one function only, so giving it to one takes it off any other.

The bindings are kept as JSON in `keybindings.conf`, in MComix' configuration directory. MComix writes that file whenever a binding is changed and again when it closes, so edit it by hand only while MComix is not running.
