Keybindings
===

Most menu items also have a hotkey for triggering them. This hotkey is noted down next to the menu label. However, some functions of the program do not have corresponding menu entries. The following tables document these functionalities and their respective hotkeys.

Opening files and moving from page to page
---

Binding | Function
--------|---------
Open file | CTRL+O
Open library | CTRL+L
Close file | CTRL+W
Next page | PageDown, LeftMouse
Next page (manga mode off) | ALT+Right, MouseWheelRight
Next page (manga mode on) | ALT+Left, MouseWheelLeft
Previous page | PageUp, Backspace
Previous page (manga mode off) | ALT+Left, MouseWheelLeft
Previous page (manga mode on) | ALT+Right, MouseWheelRight
Forward only one page (in double page mode) | CTRL plus one of the scrolling keys
Go back only one page (in double page mode) | CTRL+SHIFT plus one of the scrolling keys
First page | Pos1
Last page | End
Next archive | SHIFT+CTRL+N
Previous archive | SHIFT+CTRL+P
Next directory | CTRL+N
Previous directory | CTRL+P
Go to page | G

Reading and scrolling
---

Binding | Function
--------|---------
Scroll down | Down, KeyPadDown
Scroll up | Up, KeyPadUp
Scroll left | Left, KeyPadLeft
Scroll right | Right, KeyPadRight
Smart scroll down | Space, MouseWheelDown
Smart scroll up | SHIFT+Space, MouseWheelUp
Inverse direction of smart scrolling | X
Scroll to left, right, bottom, top | KeyPad1 to KeyPad9
Toggle fullscreen mode | F, F11
Toggle double page mode | D
Toggle manga mode | M
Toggle slideshow mode | CTRL+S
Best fit mode | B
Fit to width mode | W
Fit to height mode | H
Fixed size mode | S
Manual zoom mode | A
Stretch small images | Y
Zoom in | Plus, Equal
Zoom out | Minus
Reset zoom | CTRL+0, KeyPad0
Show OSD panel | TAB
Show magnifying lens | L, MiddleMouse
Add bookmark | CTRL+D
Edit bookmarks | CTRL+B

Other functions
---

Binding | Function
--------|---------
Quit program | CTRL+Q
Preferences | F12
Save currently opened image | CTRL+SHIFT+S
Reload currently opened directory or archive | CTRL+SHIFT+R
Minimize window | N
Hide/show all UI elements | I
Execute first, second, ... external command (see [External_Commands]) | 1 to 9

Customizing hotkeys
===================

At this time, MComix unfortunately does not have an unified keybinding editor. Due to implementation issues, the configuration is split over two files - `keybindings-gtk.rc` for menu shortcuts, and `keybindings.conf` for all other hotkeys. Do not edit these files while MComix is still running, as your changes will be overwritten when the program is closed.

For hotkeys that can be reached with a menu entry, such as "File -> Open", changing the associated keybinding is easy: Hover the mouse over the menu and press the desired key or key combination. The text should instantly update to reflect the changes to the binding.
