# Install, update and uninstall

## Install

1. Download the zip of the
    [latest release](https://github.com/ldecampos/poseRBF/releases/latest) and unzip
    it.
2. Drag `install_poseRBF.py` into a running Maya viewport.
3. Click **Install** to copy it to the scripts folder every Maya version reads, or
    **Choose Folder...** for another one.

The shelf shown gets a **poseRBF** button. No restart is needed.

## Update

Install the new version over the old one, in the same folder. The earlier copy is
replaced and the button is kept. Scenes are not touched: each RBF keeps the graph it
was made with.

## Uninstall

Delete the copied `poserbf` folder and the shelf button. The RBFs already in a scene go
on working.
