CG Cookie RetopoFlow
==========

RetopoFlow is a suite of retopology tools for Blender built by [CG Cookie](https://cgcookie.com). The tools are offered as add-on for Blender that provides a dedicated set of mesh tools designed specifically for retopology, creating a complete workflow in Blender without the need for outside applications.

RetopoFlow includes several tools, all of which automatically snap the resulting mesh to the target object surface. All mesh generation is quad-based and tools are modal. 

# Getting RetopoFlow
You may purchase RetopoFlow on the [Blender Market](https://blendermarket.com/products/retopoflow/)

Purchasing a license entitles you to tool support and helps ensure RetopoFlows continued development.

**Installation steps (from Github)**

1. To get the latest (development) version of Retopoflow, go to https://github.com/CGCookie/retopoflow/tree/b280. Mind the end of the URL, you need to get the latest changes from the **b280** branch.

2. Click on the green button "**Clone or Download**", then "**Download ZIP**"

3. Extract the **retopoflow-b280.zip** file and rename the "**retopoflow-b280**" folder to "**retopoflow**".

4. You may notice that the "**Addon_common**" folder is empty. 
Go to https://github.com/CGCookie/addon_common/tree/b280 and download the content of the repository (download the ZIP file).

5. Unzip "**addon_common-b280.zip**" and extract its content to the "**retopoflow\\Addon_common\\**" folder.

6. re-zip the "**retopoflow**" folder and install the addon normally from the **Preferences > Addons > Install** button.


# Getting Support
You can get support for tools by sending a message to CG Cookie on your [Blender Market Inbox](https://blendermarket.com/inbox).

A valid purchase is required for product support.


# Contributing
Pull requests are welcome! If you'd like to contribute to the project then simply Fork the repo, work on your changes, and then submit a pull request. We are quite strict on what we allow in, but all suggestions are welcome. If you're unsure what to contribute, then look at the [open issues](https://github.com/CGCookie/retopoflow/issues) for the current to-dos.

```
$ git clone git@github.com:CGCookie/retopoflow.git retopoflow
$ cd retopoflow
$ git checkout b280
$ git submodule update --init --recursive

# to update addon_common
$ cd retopoflow
$ git pull
$ git submodule foreach git pull
```
