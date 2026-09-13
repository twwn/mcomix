Keybindings
===

Most menu items carry a hotkey, which is shown beside the menu label. Some functions have no menu entry of their own, and some answer to keys the menus do not mention. The tables below list what every function is bound to when MComix is installed; all of it can be changed, as the last section describes.

Keys are written the way a keyboard names them. `KeyPad` is the numeric keypad, so `KeyPadHome` is the Home key on the keypad rather than the one above the arrows.

Opening files and moving from page to page
---

Function | Binding
---------|--------
Open file | CTRL+O
Open library | CTRL+L
Close file | CTRL+W
Next page | PageDown, KeyPadPageDown, LeftMouse
Previous page | PageUp, KeyPadPageUp, Backspace, BackMouse
Page to the right | ALT+Right, MouseWheelRight
Page to the left | ALT+Left, MouseWheelLeft
Forward ten pages | SHIFT+PageDown, SHIFT+KeyPadPageDown, SHIFT+ALT+Right, SHIFT+LeftMouse
Back ten pages | SHIFT+PageUp, SHIFT+KeyPadPageUp, SHIFT+Backspace, SHIFT+ALT+Left
Forward only one page (in double page mode) | CTRL+PageDown, CTRL+KeyPadPageDown
Go back only one page (in double page mode) | CTRL+PageUp, CTRL+KeyPadPageUp, CTRL+Backspace
First page | Home, KeyPadHome
Last page | End, KeyPadEnd
Go to page | G
Next archive | SHIFT+CTRL+N
Previous archive | SHIFT+CTRL+P
Next directory | CTRL+N
Previous directory | CTRL+P

In manga mode a book reads right to left, so the page to the right is the previous one and the page to the left is the next. The sideways wheel and ALT with the arrow keys follow the book that way round; PageDown and PageUp do not, and always go forward and back.

Reading and scrolling
---

Function | Binding
---------|--------
Scroll down | Down, KeyPadDown
Scroll up | Up, KeyPadUp
Scroll left | Left, KeyPadLeft
Scroll right | Right, KeyPadRight
Smart scroll down | Space, MouseWheelDown
Smart scroll up | SHIFT+Space, MouseWheelUp
Inverse direction of smart scrolling | X
Scroll to left, right, bottom, top | KeyPad1 to KeyPad9
Show magnifying lens | L, MiddleMouse
Show OSD panel | TAB, ForwardMouse

Smart scrolling is what the wheel does only while "Use smart scrolling" is on in the preferences; otherwise the wheel scrolls by a fixed number of pixels and turns the page where there is nothing left to scroll.

`BackMouse` and `ForwardMouse` are the two thumb buttons a mouse that has them marks "back" and "forward". A book has no history to move through, so back is the previous page; forward is left for the OSD panel, because the next page is already on the left mouse button.

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
Zoom in | Plus, KeyPadAdd, Equal
Zoom out | Minus, KeyPadSubtract
Reset zoom | CTRL+0, KeyPad0
Rotate 90 degrees clockwise | R
Rotate 90 degrees anticlockwise | SHIFT+R
Keep transformation between pages | K
Invert image colours | CTRL+I
Show/hide menubar | CTRL+M
Show/hide thumbnails | F9
Hide/show all UI elements | I

Escape leaves fullscreen mode unless "Escape key closes program" is on in the preferences, in which case it quits instead. Rotating by 180 degrees, flipping the page, turning autorotation off and showing or hiding the toolbar, the statusbar and the scrollbars have no key of their own until one is given to them.

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
Delete the page or the file | Delete
Undo | CTRL+Z
Redo | CTRL+Y, CTRL+SHIFT+Z
Add bookmark | CTRL+D
Edit bookmarks | CTRL+B
Minimize window | N
Quit program | CTRL+Q
Save and quit | CTRL+SHIFT+Q
Execute first, second, ... external command (see [External_Commands]) | 1 to 9

Editing an archive has no key of its own until one is given to it.

Customizing hotkeys
===================

Every binding above can be changed in the Shortcuts tab of the preferences dialog, which lists each function with the keys it answers to. Click a key to change it, then press the combination you want; an accelerator that already reaches another function is taken off that one, which the dialog says. An action can answer to more than one combination, so a function can be given a second key without losing the first.

The bindings are kept in `keybindings.conf` in MComix' configuration directory, as JSON. It is written when the program closes, so do not edit it while MComix is running.
