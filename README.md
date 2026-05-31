# UE Class Mover
A CLI tool that moves Unreal Engine C++ class files to a new subfolder and automatically fixes all the `#include` paths so nothing breaks.

## Why
Unreal projects get messy fast, especially when you just dump everything in the module root and decide later you want things organized and at some point it gets unworkable without it. Manually moving `.h`/`.cpp` files and then hunting down every broken `#include` across the whole project is annoying, so I built this to do this automatically.

JetBrains Rider's refactoring tool for moving files didn't work for me, sometimes the files would just disappear, includes kept breaking - so I just built my own. Hope the tool helps

## What it does
- Moves `.h` and `.cpp` files to a subfolder you choose
- Epic's recommended module structure: flat, Public/Private split, or all Private with subfolders
- Rewrites every `#include` across the whole project to point to the new location of the file
- Removes duplicate includes if they somehow end up in the same file
- Shows you a preview of every change before doing anything, So you can preview before making changes
- It also adds `IncludePaths` if it's missing to `Build.cs`, which means includes stay relative to the module root and you don't have to rewrite every include if you rename the project and not using Public/Private split.

## Usage

Download the UEClassMover.py file from the repo or clone it, then place it into your UE project folder - Projects\[ProjectName]

Open up the projects .sln file into a code editor of your choice and then open the terminal inside it
<br>Now if you have done the above you can leave the source path blank, if not put the Source path - Projects\[ProjectName]\Source

then run the command below
```
python UEClassMover.py
```
Enter the class names you want to move (for batch - comma separated), pick a subfolder and layout preset, confirm the preview, and it handles the rest :)

After it runs, right-click your `.uproject` -> **Generate Visual Studio Project Files**, then rebuild.

## What I Learned
- How UBT resolves include paths and custom `IncludePaths` in `Build.cs`
- regular expressions is pretty reliable if you're careful with edge cases, and for simple tasks it works

## What's next
- More layout presets and logic for that
- Maybe convert this into a Rider plugin with GUI
