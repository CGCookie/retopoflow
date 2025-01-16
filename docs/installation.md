# Installation


## Requirements

Below is a table showing which versions of Blender that you can use for each version of RetopoFlow.

| RetopoFlow |    Blender     |
| :---------- | :-------------- |
|   4.0    | 4.0 or later   |
|   3.4    | 3.6 or later   |
|   3.3    | 2.93--3.5      |
|   3.2    | 2.8x--2.9x     |
|   2.0    | 2.79 or before |

All versions of RetopoFlow are compatible with Windows, Mac, and Linux.

## Downloading

Future updates to RetopoFlow are funded by Blender Market purchases, and we provide priority support through the Blender Market support inbox.
However, we also make RetopoFlow accessible on RetopoFlow's [GitHub Page](https://github.com/CGCookie/retopoflow), especially for students, teachers, and those using RetopoFlow for educational purposes.

You may download RetopoFlow from your [account dashboard](https://blendermarket.com/account/orders) on the Blender Market once you have already purchased it or from RetopoFlow's [GitHub Releases Page](https://github.com/CGCookie/retopoflow/releases).

Important: Blender has issues with the zip files that GitHub automatically packages with the green `Code` button on the main GitHub page.
Do _not_ use the zip files created by GitHub.
Instead, use the officially packaged versions that we provide through the Blender Market or the GitHub Releases page.

The code for RetopoFlow is open source under the [GPL 3.0](https://www.gnu.org/licenses/gpl-3.0.en.html) license.
The non-code assets in this repository are not open source.


## Installing

The easiest way to install RetopoFlow is to do so directly within Blender.
You can do this by going to Edit > Preferences > Add-ons. Go to the dropdown arrow on the top right of the editor and choose Install From Disk.
This will open a File Browser in Blender, allowing to you navigate to and select the zip file you downloaded.
Press Install From Disk.

_If your browser auto-extracted the downloaded zip file, then you will need to re-compress the **RetopoFlow** folder before installing, or use Save As to save the zip file without extracting the contents._

Once installed, Blender should automatically filter the list of add-ons to show only RetopoFlow.
You can then enable the add-on by clicking the checkbox next to `RetopoFlow 4`.

If you have any issues with installing, please try the following steps:

1. Download the latest version of RetopoFlow for your version of Blender (see Requirements section above).
2. Open Blender
3. Head to Edit > Preferences > Add-ons and search for RetopoFlow
4. Expand by clicking the triangle, and then press Remove
5. Close Blender to completely clear out the previous version
6. Open Blender and head to preferences again
7. Go to the top right dropdown and click Install From Disk
8. Navigate to your RetopoFlow zip file (please do not unzip)
9. Click Install From Disk
10. Enable RetopoFlow

If you're still experiencing any issues with starting RetopoFlow, please try going to File > Defaults > Restore Factory Defaults and then try enabling RetopoFlow. This will help us rule out conflicts with other add-ons and custom settings.

## Updating

If you need to update manually for whatever reason, you can keep your preferences by copying the `RetopoFlow_keymaps.json` and `RetopoFlow_options.json` files from the previous version's folder before installation and pasting them into the new version's folder after installation.