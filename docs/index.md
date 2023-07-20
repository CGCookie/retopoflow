## Intro

RetopoFlow is a suite of Blender tools that automatically generate geometry which snaps to your source objects as you draw on the surface.
This documentation covers the installation and usage of all tools included in the add-on.

You can purchase a copy of RetopoFlow [on the Blender Market](https://blendermarket.com/products/retopoflow). 

![Blender Market](blendermarket_screenshot.png)

If you’re brand new to RetopoFlow, check the [Quick Start page](quick_start.md). Otherwise, jump right over to the Tools section.


## Requirements

Below is a table showing which versions of RetopoFlow and Blender are compatible.

| RetopoFlow |    Blender     |
| :---------- | :-------------- |
|   3.4.0    | 3.6 or later   |
|   3.3.0    | 2.93--3.5      |
|   3.2.4    | 2.8x--2.9x     |
|   2.0.3    | 2.79 or before |

All versions of RetopoFlow will work on any operating system the Blender supports.


## Installing

You may download RetopoFlow from your [account dashboard](https://blendermarket.com/account/orders) on the Blender Market, assuming you’ve already purchased it.

The easiest way to install RetopoFlow is to do so directly within Blender.
You can do this by going to Edit > Preferences > Add-ons > Install.
This will open a File Browser in Blender, allowing to you navigate to and select the zip file you downloaded.
If you are using Blender 2.8+, please make sure that the zip you select is labeled RetopoFlow 3 and **not** RetopoFlow 2.
Press Install from file.

_If your browser auto-extracted the downloaded zip file, then you will need to re-compress the **RetopoFlow** folder before installing._

Once installed, Blender should automatically filter the list of add-ons to show only RetopoFlow.
You can then enable the add-on by clicking the checkbox next to `3D View: RetopoFlow`.

![Installing RetopoFlow](install.png)

If you have any issues with installing, please try the following steps:

* Download the latest version of RetopoFlow for your version of Blender (see Requirements section above).
* Open Blender
* Head to Edit > Preferences > Add-ons and search for RetopoFlow
* Expand by clicking the triangle, and then press Remove
* Close Blender to completely clear out the previous version
* Open Blender and head to preferences again
* Click Install
* Navigate to your RetopoFlow zip file (please do not unzip)
* Click Install Add-on
* Enable RetopoFlow



## Updating

RetopoFlow 3 comes with a built-in updater.
Once you've installed it the first time, simply check for updates using the RetopoFlow menu.
If you need to update the add-on manually for any reason, please be sure to uninstall the old version and restart Blender before installing the new version. 

The RetopoFlow updater will keep all of your previous settings intact.
If you need to update manually for whatever reason, you can also keep your preferences by copying the `RetopoFlow_keymaps.json` and `RetopoFlow_options.json` files from the previous version's folder before installation and pasting them into the new version's folder after installation.

See the [Updater page](addon_updater.md) for more details.


## Getting Support

Running into a problem or have a question that the documentation isn't answering?
Reach out to us via retopoflow@cgcookie.com.

