[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$securitySid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
$systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$backendRoot = Split-Path -Parent $PSScriptRoot
$privateRoot = Join-Path $backendRoot '.local'
$targets = @((Get-Item -LiteralPath (Join-Path $backendRoot '.env')))
if (Test-Path -LiteralPath $privateRoot) {
 $targets += Get-Item -LiteralPath $privateRoot
 $targets += Get-ChildItem -LiteralPath $privateRoot -Force -Recurse
}
foreach ($databaseName in @('fees.db','fees.db-wal','fees.db-shm')) {
 $databasePath = Join-Path $backendRoot $databaseName
 if (Test-Path -LiteralPath $databasePath) { $targets += Get-Item -LiteralPath $databasePath }
}
foreach ($target in $targets) {
 if ($target.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Private files must not be reparse points' }
 if ($target.PSIsContainer) {
  $acl = [Security.AccessControl.DirectorySecurity]::new()
  $acl.SetAccessRuleProtection($true,$false)
  foreach ($sid in @($securitySid,$systemSid)) {
   $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
  }
 } else {
  $acl = [Security.AccessControl.FileSecurity]::new()
  $acl.SetAccessRuleProtection($true,$false)
  foreach ($sid in @($securitySid,$systemSid)) {
   $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow))
  }
 }
 Set-Acl -LiteralPath $target.FullName -AclObject $acl
 $rules = (Get-Acl -LiteralPath $target.FullName).Access
 if ($rules.Count -ne 2) { throw 'Private ACL verification failed' }
 foreach ($rule in $rules) {
  $resolvedSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
  if ($resolvedSid -notin @($securitySid.Value,$systemSid.Value) -or $rule.AccessControlType -ne 'Allow') { throw 'Unexpected private access rule' }
 }
}
Write-Output "Private file permissions verified for $($targets.Count) files and directories."
