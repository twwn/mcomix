External commands
===

Overview
---

Sometimes, MComix might not provide enough functionality for certain needs - you might want to retouch a page in an image editor, or to open a file manager at the location of the currently opened images to perform some move operations.

MComix provides for such cases by allowing the user to define a list of external commands that can be executed at will. The relevant menu can be accessed via "File&rarr;Open with". Initially, this submenu will be empty. New commands can be added with the "Edit commands" menu item. After one or more commands have been specified, they can be executed either via menu entry, or by pressing the 1 to 9 keys. Those activate the first to ninth command, respectively.

Add and edit commands
---

The edit window first displays a list of all commands, and a few buttons to edit those commands. 

[[img src="mcomix-external-commands.png" alt="Edit external commands"]]

Each command consists of four parts:

- *Label*: The name the command will be listed as in the menu.
- *Command*: The executable that is to be run, followed by zero or more arguments, all separated by spaces. If an argument contains spaces, wrap it in quotation marks. The command can contain certain variables, as listed under *Variables* further down. 
- *Working directory*: The command will be executed in this directory. Only one directory is allowed. If the directory contains spaces, wrap it with quotation marks.
- *Disabled in archives*: If this box is ticked, the command will not be run when an archive is currently opened. This helps prevent accidentally working on temporary files that will be deleted as soon as the archive is closed.

Variables
---

The following variables can be inserted into the command and working directory fields. When a command is run, these variables will be substituted with their respective special meaning.

#### Image-related variables

Variable | Meaning | Example
---------|---------|--------
%F | Absolute path to the currently opened image file | /home/user/Downloads/cats.jpg
%f | Name of the currently opened image file | cats.jpg
%D | Absolute path to the directory containing the currently opened image file | /home/user/Downloads
%d | Name of the directory containing the currently opened image file | Downloads

These variables will expand to temporary filenames and directories when used in conjunction with archives.

#### Archive-related variables

These variables are only valid if an archive is opened when the command is executed.

Variable | Meaning | Example
---------|---------|--------
%A | Absolute path to the currently opened archive | /home/user/comic-2012.zip
%a | Name of the currently opened archive | comic-2012.zip
%C | Absolute path of the directory containing the currently opened archive | /home/user
%c | Name of the directory containing the currently opened archive | user

#### Container-related variables

These variables expand differently depending on whether an archive or a directory is opened when the command is executed. (Think of it as B as in "book" and S as in "shelf".)

Variable | Meaning | Directory Example | Archive Example
---------|---------|-------------------|----------------
%B | Absolute path to the directory containing the currently opened image file, or absolute path to the currently opened archive | /home/user/Downloads | /home/user/comic-2012.zip
%b | Name of the directory containing the currently opened image file, or name of the currently opened archive | Downloads | comic-2012.zip
%S | Absolute path of the directory containing the currently opened directory or archive | /home/user | /home/user
%s | Name of the directory containing the currently opened directory or archive | user | user

#### Miscellaneous variables

Use these variables to insert special meta characters that MComix uses for variable substitution.

Variable | Meaning | Example
---------|---------|--------
%/ | Inserts a backslash or slash, depending on operating system. Windows users will see a backslash, others a forward slash. | /
%" | Insert a literal quote | "
%% | Insert a literal percent character | %