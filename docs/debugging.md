# RetopoFlow Debugging

If you run into an issue while using RetopoFlow, you can report it via [Product Support](https://blendermarket.com/products/retopoflow) on Blender Market or by creating an issue via GitHub RetopoFlow [Issues](https://github.com/CGCookie/retopoflow/issues/new/choose).
These RetopoFlow issues covers bugs within RetopoFlow or unexpected behavior of tools.

Note: support via GitHub will be limited to fixing RetopoFlow bugs.
The Blender Market route will provide you premium support.

Whichever path of support you take, there are a few things to keep in mind to help us in debugging and fixing the issue as quickly as possible.
The list below contain a few of these.

- Explain clearly the context.  For example, add a screenshot or share a .blend file that shows what the scene looked like before you had the issue, what action you did to cause the issue, and what was the result of the action.

- Consider sharing your .blend file with us.  Often times, the .blend file has a particular setting that we have not tested, and having access to your file will make reproducing your issue easier.

- Try to reproduce the issue on the default Blender scene, or try to reproduce the issue on another machine, especially a different system (OSX, Windows, Linux) if possible.

- Be sure to include all of the terminal / console output in your post (see below).

- Be sure to include the machine information, Blender version, and RetopoFlow version in your post.

- Be sure to reply to our questions.  If we are unable to reproduce the issue, and it goes without any activity for a time, we will close the issue.


## Terminal / Console Output

Sometimes an issue is caused by a different part of code than what is reported.
By design, we do not report all the information in RetopoFlow, but that information might be critical to solving the issue.
You can access the additional information through the system terminal / console.

Note: There might be a lot of info in there (have to scroll), so be sure to copy _all_ of the text from the terminal / console.

### Windows

- Start Blender as usual
- In the Blender Menu: Windows > Toggle System Console.  The system console window will now open; minimize for now.
- Start RetopoFlow
- Once issue occurs, switch to the system console.

### OSX

Option 1:

- Right click on Blender app (ex: in Applications), then click New Terminal at Folder.  The system terminal window will now open.
- In the terminal, type `./Contents/MacOS/Blender` to start Blender.
- Start RetopoFlow
- Once issue occurs, switch to the system terminal.

Option 2:

- Open Terminal (Command+Space, type Terminal)
- Open Finder, and browse to the Blender app.
- Right click on Blender, then click Show Package Contents.
- Open Contents folder, then open MacOS folder
- Drag the blender file to the Terminal window
- In Terminal, press enter.
- Start RetopoFlow
- Once issue occurs, switch to the system terminal.

### Linux

Option 1:

- Right click Blender app
- Choose Edit Application
- Under Advanced tab, check "Run in terminal"
- Save and close
- Start Blender as normal, but now a terminal window will show right before Blender loads.
- Start RetopoFlow
- Once issue occurs, switch to the system terminal.

Option 2:

- Open system terminal / console
- Type `/path/to/blender`, where `/path/to` is the path to the blender binary.
  ex: `/home/username/Downloads/Blender\ 3.0.1/blender`
  ex: `/usr/bin/blender`
- Start RetopoFlow
- Once issue occurs, switch to the system terminal / console

