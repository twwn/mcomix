External commands
===

Overview
---

MComix can run programs of your choosing on the file that is open: an image editor to retouch a page, a file manager at the book's location, or a script of your own. They are listed under "File &rarr; Open with", which also has "Edit commands" to set them up. The number keys 1 to 9 run the first nine commands in the list.

Add and edit commands
---

![Edit external commands](images/mcomix-external-commands.png)

"Add" puts a new command in the list, and "Add separator" a line that divides the menu; "Remove", "Up" and "Down" act on the selected row, which can also be dragged to another place. Each command has four fields:

- *Label*: the name the command has in the menu.
- *Command*: the program to run, followed by its arguments, separated by spaces. An argument that contains spaces goes in quotation marks. The variables below stand for the file that is open, and environment variables such as `$HOME` are expanded as well.
- *Working directory*: the directory the command runs in, written the same way. Leave it empty to run the command where MComix was started.
- *Disabled in archives*: the command does not run while an archive is open, which keeps it from working on the temporary files MComix deletes when the archive is closed.

"Preview" shows the selected command as it would run on the page that is open, and says so where the program or the working directory cannot be found; "Run command" runs it. "Save" keeps the list; closing the editor with changes that are not saved asks whether to keep them.

Variables
---

When a command runs, each variable in its command and working directory is replaced by the path or name it stands for.

#### Image-related variables

With an archive open, these name the temporary files MComix has unpacked the pages to.

Variable | Meaning | Example
---------|---------|--------
%F | Absolute path to the currently opened image file | /home/user/Downloads/cats.jpg
%f | Name of the currently opened image file | cats.jpg
%D | Absolute path to the directory containing the currently opened image file | /home/user/Downloads
%d | Name of the directory containing the currently opened image file | Downloads

#### Archive-related variables

These can only be used while an archive is open.

Variable | Meaning | Example
---------|---------|--------
%A | Absolute path to the currently opened archive | /home/user/comic-2012.zip
%a | Name of the currently opened archive | comic-2012.zip
%C | Absolute path of the directory containing the currently opened archive | /home/user
%c | Name of the directory containing the currently opened archive | user

#### Container-related variables

These stand for the archive where one is open, and for the directory of images otherwise. B is for "book", and S for "shelf".

Variable | Meaning | Directory Example | Archive Example
---------|---------|-------------------|----------------
%B | Absolute path to the directory containing the currently opened image file, or absolute path to the currently opened archive | /home/user/Downloads | /home/user/comic-2012.zip
%b | Name of the directory containing the currently opened image file, or name of the currently opened archive | Downloads | comic-2012.zip
%S | Absolute path of the directory containing the currently opened directory or archive | /home/user | /home/user
%s | Name of the directory containing the currently opened directory or archive | user | user

#### Miscellaneous variables

Variable | Meaning | Example
---------|---------|--------
%/ | The directory separator: a backslash on Windows, a slash elsewhere | /
%" | A literal quotation mark | "
%% | A literal per cent sign | %
