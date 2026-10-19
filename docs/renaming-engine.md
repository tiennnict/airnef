# File Renaming Engine

> Docs: [README](../README.md) · [Installation](installation.md) · [Camera setup](camera-setup.md) · [User guide](user-guide.md) · [Renaming engine](renaming-engine.md) · [Command line](command-line-reference.md) · [FAQ](faq.md)

Airnef allows you to customize the names of directories and filenames for the images you download via a simple, mini-scripting language, accessible via the the --dirnamespec and --filenamespec command line options. You can enter these options in the 'Additional arguments' field of the GUI. Below are some examples to help get you started.

Include the model of the camera in the downloaded filename.  
Sample Output: D7200_DSC_0119.NEF  

```text
--filenamespec @cameramodel@_@filename@
```

Create a directory based on the capture date of each file and a filename based on the sequence number of each download (ie, first download seq # is 0001, second is 0002, etc..).  
Sample Output: 20150928\Photo-0001.JPG  

```text
--dirnamespec @capturedate@ --filenamespec Photo-@dlnum@.@filename_ext@
```

Include a custom name for the camera based on the serial number. For example if you have two cameras, one with S/N 7104765 and another with 5462197 and you'd like images from the first camera to have "MyCamera" in the name and images from the second to have "JillsCamera". Note that the S/N Airnef uses is the one the camera reports via the wireless interface, which may have more or fewer digits than the S/N printed on the camera - you can view the serial number that Airnef uses in a download transfer report.  
Sample Output: MyCamera_DSC_1125.NEF, JillsCamera_DSC_2535.NEF  
`--filenamespec` `@cameraserial@@replace~7104765~MyCamera@@replace~5462197~JillsCamera@_@filename@`

## Specification Reference

### `--filenamespec` spec and --dirnamespec spec (added in v1.1)

Rename downloaded files using Airnef's renaming engine. Place spec in quotes if it contains any literal spaces. This can be applied to the filename and/or the directory (tree) where the file is stored. 'spec' contains your desired output name including optional specifiers, which offer the ability to insert dynamic data into the filename, such as the camera model, serial number, capture date, etc.. Each specifier is enclosed in @@ and can optionally include subscripts to only use a portion of the dynamic data and also options to change elements such as case. If you'd like preview/test your --dirnamespec and --filenamespec before attempting a download then use --action listfiles. The directory listing will show a preview of what the output directory/filename name will look like. Here is the full format of a specifier; everything after specifier name is optional:

@**specifiername**:**subscript_start**:**subscript_end**:**options**@

Here is the full list of support specifiers:

| **Specifier** | **Description** | **Example** |
|---|---|---|
| **Capture Date/Time Specifiers** |  |  |
| @capturedate@ | Capture date of file in yyyymmdd format | 20150924 |
| @capturedate_m@ | Capture date of file (month) in mm format | 09 |
| @capturedate_d@ | Capture date of file (day) in dd format | 24 |
| @capturedate_y@ | Capture date of file (year) in yyyy format | 2015 |
| @capturedate_dow@ | Capture date of file (day of week, numeric) [Monday=1, Tuesday=2...Sunday=7] | 4 |
| @capturedate_woy@ | Capture date of file (week of year) . Monday considered first day of week | 38 |
| @capturedate_month@ | Capture date of file (month, text) | September |
| @capturedate_dayofweek@ | Capture date of file (day of week, text) | Thursday |
| @capturedate_season@ | Capture season (Spring, Summer, Fall, or Winter) | Fall |
| @capturetime@ | Capture time of file in hhmmss format | 140513 |
| @capturetime_h@ | Capture time (hour) of file in hh format | 14 |
| @capturetime_m@ | Capture time (minute) of file in mm format | 05 |
| @capturetime_s@ | Capture time (seconds) of file in ss format | 13 |
| **Download Date/Time Specifiers. The airnefcmd launch date/time is used as the download date/time for all files downloaded in the session** |  |  |
| @dldate@ | Download date of file in yyyymmdd format | 20150924 |
| @dldate_m@ | Download date of file (month) in mm format | 09 |
| @dldate_d@ | Download date of file (day) in dd format | 24 |
| @dldate_y@ | Download date of file (year) in yyyy format | 2015 |
| @dldate_dow@ | Download date of file (day of week, numeric) [Monday=1, Tuesday=2...Sunday=7] | 4 |
| @dldate_woy@ | Download date of file (week of year) . Monday considered first day of week | 38 |
| @dldate_month@ | Download date of file (month, text) | September |
| @dldate_dayofweek@ | Download date of file (day of week, text) | Thursday |
| @dldate_season@ | Download season (Spring, Summer, Fall, or Winter) | Fall |
| @dltime@ | Download time of file in hhmmss format | 140513 |
| @dltime_h@ | Download time (hour) of file in hh format | 14 |
| @dltime_m@ | Download time (minute) of file in mm format | 05 |
| @dltime_s@ | Download time (seconds) of file in ss format | 13 |
| **Capture Filename/Folder/Media Card Specifiers** |  |  |
| @pf@ | Shortcut to @path@/@filename@ | c:\pics\DSC_0014.NEF |
| @path@ | Directory to local file (equal to --outputdir if no --dirnamespec, otherwise generated --dirnamespec for use by --filenamespec) | c:\pics |
| @filename@ | Local filename (full). Local filename can be different than capturefilename if download small or large thumbnails | DSC_0014.NEF |
| @filename_root@ | Local filename (root, without extension) | DSC_0014 |
| @filename_ext@ | Local filename (extension) | NEF |
| @capturefilename@ | Capture filename (full) | DSC_0014.NEF |
| @capturefilename_root@ | Capture filename (root, without extension) | DSC_0014 |
| @capturefilename_ext@ | Capture filename (extension) | NEF |
| @camerafolder@ | Camera folder of filename | 100D7200 |
| @slotnumber@ | Media card slot # file downloaded from (1 or 2) | 1 |
| **Camera Make/Model/Serial Specifiers** |  |  |
| @cameramake@ | Camera Make | Nikon |
| @cameramodel@ | Camera Model | D7200 |
| @cameraserial@ | Camera Serial Number | 35551323 |
| **Download File Number Specifiers** |  |  |
| @dlnum@ | The nth file downloaded this Airnef session (1..number of files downloaded) | 0045 |
| @dlnum_lifetime@ | The nth file downloaded for this camera model+serial for lifetime of Airnef | 5345 |
| **Meta Specifiers** |  |  |
| @replace~xxx~yyy@ | Replace every occurence of 'xxx' with 'yyy' for output string generated up to this point | @replace~NEF~Raws@ converts "NEF" to "Raws" |
| @replacere~xxx~yyy@ | Regular Express version of @replace. This uses the Python re.sub() function. |  |
| @@ | Literal '@' | @ |

When both --dirnamespec and --filenamespec are specified, --dirnamespec is processed first. The output of --dirnamespec is then available as the updated @path@ for --filename spec. For example, if you use "--outputdir c:\pics --dirnamespec @cameramake@ --filenamespec whatever" with a Nikon camera, when --dirnamespec is processed the @path@ specifier translates to c:\pics. When --filenamespec is processed the @path@ specifier translates to c:\pics\Nikon

All specifiers except @replace@ can include optional subscripts to select a subset of characters from the generated specifier string. The first subscript is the starting character position. The second subscript is the ending character position (exclusive). An empty first subscript implies from the beginning of the string. An empty second subscript implies to the end of the string. Subscript values can be negative, which count from the end of the string.

Here are some examples based on a sample filename of DSC_0014.NEF:

| **Example** | **What it Does** | **Output** |
|---|---|---|
| @filename:4:8@ | Extract characters 4 through 7 | 0014 |
| @filename::3@ | Extract characters from beginning through 2 | DSC |
| @filename:4:@ | Extract characters 4 through end | 0014.NEF |
| @filename:-3:@ | Extract last three characters | NEF |
| @filename:-3:-2@ | Extract one character starting 3 from the end | N |

The case of any specifier's output can be changed via the options field. The only exceptions are the @replace@ specifiers which uses the entire entered case. The options field is after the two subscript fields - if no subscripts are required than use three ':' as placeholders to skip past them. Here are the available options:

| **Option** | **What it Does** |
|---|---|
| u | Entire specifier output is uppercased |
| l | Entire specifier output is lowercased |
| c | First character of specifier output is capitalized |

Here are some case examples based on a camera make of "Nikon":

| **Example** | **What it Does** | **Output** |
|---|---|---|
| @cameramake:::u@ | Entire specifier output is uppercase | NIKON |
| @cameramake:::l@ | Entire specifier output is lowercase | nikon |
| @cameramake:::c@ | First character of specifier output is capitalized | Nikon |

The @replace@ specifier is very powerful and allows you to perform search/replacement operations. It is performed on the generated output string at the point where the @replace@ occurs. This means it is performed after any other specifier replacements up to that point. Here are examples:

| **Example** | **Sample Input** | **Output** |
|---|---|---|
| --filenamespec @cameraserial@@replace~35551323~Main Camera@_@dlnum@@filename_ext@ | Serial #35551323, DSC_0014.NEF | "Main Camera_0001.NEF" |
| --dirnamespec @cameramodel@\@filename_ext@@replace~NEF~Raw Files@ | D7200 and DSC_0014.NEF | "D7200\Raw Files" (output directory) |

The directory name generated by --dirnamespec is relative to --outputdir (if specified) and can can include multiple directories - airnefcmd will recurse to generate the necessary tree of subdirectories for any directory that doesn't already exist within the path. For example, --outputdir c:\mypics --dirnamespec "@cameramodel@\@cameramake@\@cameraserial@" will create (if necessary) the directories c:\mypics\Nikon, c:\mypics\Nikon\D7200, and c:\mypics\Nikon\D7200\35551323. After processing --dirnamespec the resulting directory name/path is converted to an absolute path.
