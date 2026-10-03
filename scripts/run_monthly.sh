#!/bin/sh
# Called by launchd every morning; decides whether today is a day to do anything.
#   4th of the month        full refresh (Bank of England approvals are out, HMRC has the month before)
#   17th-25th               only if Land Registry has published a new month (--if-new exits at once otherwise)
# The result is logged and shown as a macOS notification. Publishing the Artifact stays a manual step.
cd "$(dirname "$0")/.." || exit 1
day=$(date +%d)
case "$day" in
  04) args="" ;;
  17|18|19|20|21|22|23|24|25) args="--if-new" ;;
  *) exit 0 ;;
esac
mkdir -p data/processed/logs
out=$(python3 scripts/update_monthly.py $args 2>&1)
code=$?
printf '%s\n' "$out" >> data/processed/logs/launchd.log
case "$out" in
  *"nothing to do"*) exit 0 ;;
esac
if [ $code -eq 0 ]; then
  msg="房价和市场雷达数据已更新，等你发布"
else
  msg="更新有步骤失败，看 data/processed/logs"
fi
osascript -e "display notification \"$msg\" with title \"伦敦买房地图\"" 2>/dev/null
exit $code
