# Retopoflow Debugging

If you run into an issue while using Retopoflow, you can report it via [Product Support](https://blendermarket.com/products/retopoflow) on Superhive (formerly Blender Market) or by creating an issue on [GitHub](https://github.com/CGCookie/retopoflow/issues/new/choose).

Those who have purchased Retopoflow are helped first. 

We support official releases of Blender (as listed on the [Installation](./installation.html) page) and cannot gurantee compatibility with pre-release or non-official versions of Blender or compatibility with other add-ons. 

There are a few things to keep in mind that will help us in debugging and fixing the issue as quickly as possible.

- Clearly explain the context.  Show or describe what the scene looked like before you had the issue, what action triggered the issue, and what was the result of the action.

- Consider sharing your `.blend` file with us.  Often times, the file has a particular combination of Blender settings that we have not tested and having access to your file will make reproducing your issue easier.

- Try to reproduce the issue on the default Blender scene or try to reproduce the issue on another machine, especially a different operating system (OSX, Windows, Linux) if possible.

- Be sure to include all of the terminal / console output in your message (see below).

- Be sure to include your machine information, Blender version, and Retopoflow version in your message.

- Be sure to reply to our questions.  If we are unable to reproduce the issue and it goes without any activity for some time, we will close the issue.


## Terminal / Console Output

Sometimes an issue is caused by a different part of code than what is reported by the error in the UI.

By design, we do not report all the information from Retopoflow, but that information might be critical to solving the issue.
You can access the additional information through the system terminal / console.

Note: There might be a lot of info in there (have to scroll), but be sure to copy _all_ of the text from the terminal / console. It's ok to hit us with a wall of text! 

<!--
### Built-in Deep Debugging

This simplest way to report the terminal output is to enable Deep Debugging.

Note: you will need to restart Blender after enabling.

![](images/debugging_enable.png)


When Deep Debugging is enabled, all terminal output will be redirected to a text file.

- Start Blender, enabled Deep Debugging, restart Blender
- Start Retopoflow
- Once issue occurs, exit Retopoflow
- Under the Retopoflow menu, choose Open Debugging Info

![](images/debugging_open.png)
-->

### Windows

- Start Blender as usual
- In the Blender Menu: Windows > Toggle System Console.  The system console window will now open; minimize for now.
- Start Retopoflow
- Once issue occurs, switch to the system console.

### OSX

Option 1:

- Right click on Blender app (ex: in Applications), then click New Terminal at Folder.  The system terminal window will now open.
- In the terminal, type `./Contents/MacOS/Blender` to start Blender.
- Start Retopoflow
- Once issue occurs, switch to the system terminal.

Option 2:

- Open Terminal (Command+Space, type Terminal)
- Open Finder, and browse to the Blender app.
- Right click on Blender, then click Show Package Contents.
- Open Contents folder, then open MacOS folder
- Drag the blender file to the Terminal window
- In Terminal, press enter.
- Start Retopoflow
- Once issue occurs, switch to the system terminal.

### Linux

Option 1:

- Right click Blender app
- Choose Edit Application
- Under Advanced tab, check "Run in terminal"
- Save and close
- Start Blender as normal, but now a terminal window will show right before Blender loads.
- Start Retopoflow
- Once issue occurs, switch to the system terminal.

Option 2:

- Open system terminal / console
- Type `/path/to/blender`, where `/path/to` is the path to the blender binary.
  ex: `/home/username/Downloads/Blender\ 3.0.1/blender`
  ex: `/usr/bin/blender`
- Start Retopoflow
- Once issue occurs, switch to the system terminal / console

