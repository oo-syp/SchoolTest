@echo off
rem Открыть порт SchoolTest в брандмауэре Windows.
rem Запускать от имени администратора на компьютере, где работает SchoolTest.exe
set PORT=8081
if not "%1"=="" set PORT=%1
net session >nul 2>&1
if errorlevel 1 (
  echo Запустите этот файл от имени администратора:
  echo правая кнопка мыши - "Запуск от имени администратора".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="SchoolTest" >nul 2>&1
netsh advfirewall firewall add rule name="SchoolTest" dir=in action=allow protocol=TCP localport=%PORT% profile=private,domain
echo Порт %PORT% открыт для локальной сети (профили "Частная" и "Доменная").
pause
