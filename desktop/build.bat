@echo off
echo Building OpenCode Pet Desktop App...
pyinstaller --noconfirm --onefile --windowed --name "OpenCodePet" --icon "%CD%\desktop\pet.ico" --add-data "desktop\sprites;sprites" --add-data "desktop\main.py;desktop" --add-data "desktop\control.html;desktop" --add-data "desktop\app.html;desktop" desktop\main.py
echo Done. Executable: dist\OpenCodePet.exe
pause
