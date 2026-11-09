Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Dell\Desktop\bot grok"
WshShell.Run "cmd /c powershell -Command ""Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*master_daemon.py*' -or $_.CommandLine -like '*hourly_swing_agent.py*' -or $_.CommandLine -like '*buda_market_maker_sim.py*' -or $_.CommandLine -like '*cash_carry_sim.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"" && timeout /t 1 >nul && py -3.12 master_daemon.py", 0, False
