$Body = @{host="native"; scan_state="intact"; content_form="literal"} | ConvertTo-Json
(Invoke-RestMethod -Method Post -Uri "http://localhost:8765/api/content/run" -ContentType "application/json" -Body $Body).flag
