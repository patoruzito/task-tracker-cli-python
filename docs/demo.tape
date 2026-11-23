Output docs/demo.gif

Set FontSize 18
Set Width 1000
Set Height 520
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms

Hide
Type "export TASK_CLI_FILE=/tmp/demo-tasks.json && rm -f $TASK_CLI_FILE && clear"
Enter
Show

Type 'task-cli add "Buy groceries"'
Enter
Sleep 800ms
Type 'task-cli add "Write README"'
Enter
Sleep 800ms
Type 'task-cli add "Study argparse"'
Enter
Sleep 800ms
Type "task-cli mark-in-progress 2"
Enter
Sleep 800ms
Type "task-cli mark-done 1"
Enter
Sleep 800ms
Type "task-cli list"
Enter
Sleep 2s
Type "task-cli list done"
Enter
Sleep 1.5s
Type "task-cli delete 99"
Enter
Sleep 2.5s
