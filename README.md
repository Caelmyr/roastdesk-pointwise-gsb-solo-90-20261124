# RoastDesk

RoastDesk is a local photo workbench for visual roast-color checks on coffee bean trays.

Run `./start.sh`, then open [RoastDesk](http://127.0.0.1:19893/). The named data
volume stays available after `./start.sh stop`. The same desk can run with
`python -m roastdesk` on a Python 3.11 or 3.12 environment with the locked dependencies.

1. Import one overhead PNG or JPEG or open the labeled synthetic tray.
2. Set a crop by clicking two image corners. Update the tray separator and minimum
   area. Every contiguous dark footprint becomes one measured shape.
3. Click a source pixel or a table position to confirm what the photo shows. Inspect
   each shape's area, mean RGB, brightness and roast color band. Exclude sample
   fragments or bring them back. The histogram and summary count each included
   bean once. Crop or separator changes clear exclusions tied to the prior shapes.
4. Save the current setup for this tray. Save an inspection to retain its original
   settings and measurements in an immutable archive. Reopen it and download the
   original image, bean table or marked PNG.
5. Use Photo preparation for input alignment, composition and tonal correction.
   Its current result can open a new tray inspection while preserving preparation provenance.

Source coordinates are on the displayed-orientation RGB image. Use opaque, single
frame images of 8–4096 pixels per side, 4 million pixels and 14 MiB maximum, with up
to 320 measurable components in the crop. Use a pale matte tray and even lighting.
The reported lightness is weighted brightness in photo code values, suitable for
relative comparison under the same capture setup. Physical roast scales require
external calibration.
