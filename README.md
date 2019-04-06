CG Cookie RetopoFlow
==========

RetopoFlow is a suite of retopology tools for Blender built by [CG Cookie](https://cgcookie.com). The tools are offered as add-on for Blender that provides a dedicated set of mesh tools designed specifically for retopology, creating a complete workflow in Blender without the need for outside applications.

RetopoFlow includes several tools, all of which automatically snap the resulting mesh to the target object surface. All mesh generation is quad-based and tools are modal. 

# Getting RetopoFlow
You may purchase RetopoFlow on the [Blender Market](https://blendermarket.com/products/retopoflow/)

Purchasing a license entitles you to tool support and helps ensure RetopoFlows continued development.


## Getting Support
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
$ git submodule foreach git pull origin master
```
