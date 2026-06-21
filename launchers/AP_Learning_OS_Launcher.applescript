property blackboardAgentSource : "/Users/zxydediannao/Downloads/ AP Master Library/AP_Learning_OS/launchers/com.aplearningos.blackboard.plist"
property blackboardAgentTarget : "/Users/zxydediannao/Library/LaunchAgents/com.aplearningos.blackboard.plist"
property blackboardURL : "http://127.0.0.1:8765"
property sessionsPath : "/Users/zxydediannao/Downloads/ AP Master Library/AP_Learning_OS/sessions"

on run
	set actionList to {"打开黑板", "打开证据包目录", "退出"}
	set picked to choose from list actionList with title "AP Learning OS" with prompt "选择操作：" default items {"打开黑板"}
	if picked is false then return
	set actionName to item 1 of picked
	
	if actionName is "打开黑板" then
		my openBlackboard()
	else if actionName is "打开证据包目录" then
		do shell script "open " & quoted form of sessionsPath
	end if
end run

on openBlackboard()
	do shell script "mkdir -p " & quoted form of "/Users/zxydediannao/Library/LaunchAgents"
	do shell script "cp " & quoted form of blackboardAgentSource & " " & quoted form of blackboardAgentTarget
	do shell script "launchctl bootstrap gui/$(id -u) " & quoted form of blackboardAgentTarget & " 2>/dev/null || true"
	do shell script "launchctl kickstart -k gui/$(id -u)/com.aplearningos.blackboard 2>/dev/null || true"
	delay 1
	do shell script "open " & quoted form of blackboardURL
end openBlackboard
