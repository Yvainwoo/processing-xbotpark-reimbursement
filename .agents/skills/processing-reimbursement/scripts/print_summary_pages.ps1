param(
  [Parameter(Mandatory = $true)][string]$TemplatePptx,
  [Parameter(Mandatory = $true)][string]$JobsJson,
  [string]$ProjectName = '儿童手工',
  [ValidateRange(1, 60)][int]$WaitSeconds = 20,
  [switch]$PrepareOnly
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Read-SlideXml([string]$pptxPath) {
  $zip = [System.IO.Compression.ZipFile]::OpenRead($pptxPath)
  try {
    $entry = $zip.GetEntry('ppt/slides/slide1.xml')
    if ($null -eq $entry) { throw "PPTX 缺少 slide1.xml：$pptxPath" }
    $reader = [System.IO.StreamReader]::new($entry.Open(), [System.Text.UTF8Encoding]::new($false), $true)
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
  } finally { $zip.Dispose() }
}

function Write-SlideXml([string]$pptxPath, [string]$slideXml) {
  $zip = [System.IO.Compression.ZipFile]::Open($pptxPath, [System.IO.Compression.ZipArchiveMode]::Update)
  try {
    $entry = $zip.GetEntry('ppt/slides/slide1.xml')
    if ($null -eq $entry) { throw "PPTX 缺少 slide1.xml：$pptxPath" }
    $entry.Delete()
    $newEntry = $zip.CreateEntry('ppt/slides/slide1.xml', [System.IO.Compression.CompressionLevel]::Optimal)
    $writer = [System.IO.StreamWriter]::new($newEntry.Open(), [System.Text.UTF8Encoding]::new($false))
    try { $writer.Write($slideXml) } finally { $writer.Dispose() }
  } finally { $zip.Dispose() }
}

$templatePath = (Resolve-Path -LiteralPath $TemplatePptx).Path
$templateXml = Read-SlideXml $templatePath
if (([regex]::Matches($templateXml, [regex]::Escape($ProjectName))).Count -ne 1 -or
    ([regex]::Matches($templateXml, 'XXX')).Count -ne 1) {
  throw '模板中项目名称或金额占位符不唯一；请检查模板后再打印。'
}
$jobs = @(Get-Content -LiteralPath $JobsJson -Raw -Encoding UTF8 | ConvertFrom-Json)
if ($jobs.Count -eq 0) { throw '没有待打印的信息概要页。' }
$prepared = @()
foreach ($job in $jobs) {
  $categoryText = [string]$job.category
  $amountText = [string]$job.amount
  if (-not $categoryText.Trim() -or $amountText -notmatch '^\d+(\.\d{1,2})?$') {
    throw "费用类型或金额无效：$categoryText / $amountText"
  }
  if (-not $job.work_pptx -or -not $job.output_pdf) { throw "缺少输出路径：$categoryText" }
  $workPath = [System.IO.Path]::GetFullPath([string]$job.work_pptx)
  $outputPath = [System.IO.Path]::GetFullPath([string]$job.output_pdf)
  if (Test-Path -LiteralPath $workPath) { throw "拒绝覆盖已有工作 PPTX：$workPath" }
  if (Test-Path -LiteralPath $outputPath) { throw "拒绝覆盖已有 PDF：$outputPath" }
  $replacementProject = "$ProjectName（$categoryText）"
  $updatedXml = $templateXml.Replace($ProjectName, $replacementProject).Replace('XXX', $amountText)
  if ($updatedXml.Replace($replacementProject, $ProjectName).Replace($amountText, 'XXX') -cne $templateXml) {
    throw "替换后样式审计失败：$categoryText"
  }
  $prepared += [pscustomobject]@{ WorkPath=$workPath; OutputPath=$outputPath; UpdatedXml=$updatedXml; Category=$categoryText }
}

# 全部预检通过后再制作工作副本。只改两处 XML 文本，并在打印前核验。
foreach ($item in $prepared) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $item.WorkPath) | Out-Null
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $item.OutputPath) | Out-Null
  Copy-Item -LiteralPath $templatePath -Destination $item.WorkPath
  Write-SlideXml $item.WorkPath $item.UpdatedXml
  if ((Read-SlideXml $item.WorkPath) -cne $item.UpdatedXml) {
    throw "工作 PPTX 写入校验失败：$($item.Category)"
  }
}
if ($PrepareOnly) {
  Write-Output "已准备 $($prepared.Count) 份 PPTX；打印前样式审计通过。"
  return
}

$defaultPrinter = Get-CimInstance Win32_Printer | Where-Object { $_.Default } | Select-Object -First 1
if ($null -eq $defaultPrinter -or $defaultPrinter.Name -ne 'Microsoft Print to PDF') {
  $actualName = if ($null -eq $defaultPrinter) { '<无默认打印机>' } else { [string]$defaultPrinter.Name }
  throw "当前 Windows 默认打印机不是 Microsoft Print to PDF：$actualName"
}
$paperSize = (Get-PrintConfiguration -PrinterName 'Microsoft Print to PDF').PaperSize
if ([string]$paperSize -ne 'A4') { throw "PDF 打印机纸张不是 A4：$paperSize" }

$ppt = $null
try {
  # 一次启动 PowerPoint，依次打印所有类型；只读打开，不保存工作副本。
  $ppt = New-Object -ComObject PowerPoint.Application
  $ppt.DisplayAlerts = 1
  foreach ($item in $prepared) {
    $presentation = $null
    try {
      $presentation = $ppt.Presentations.Open($item.WorkPath, $true, $false, $false)
      $presentation.PrintOptions.OutputType = 1
      $presentation.PrintOptions.FitToPage = -1
      $presentation.PrintOptions.FrameSlides = 0
      $presentation.PrintOptions.PrintInBackground = 0
      $presentation.PrintOut(1, 1, $item.OutputPath, 1, 0)
      $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
      while ((-not (Test-Path -LiteralPath $item.OutputPath) -or
          (Get-Item -LiteralPath $item.OutputPath).Length -eq 0) -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
      }
      if (-not (Test-Path -LiteralPath $item.OutputPath) -or
          (Get-Item -LiteralPath $item.OutputPath).Length -eq 0) {
        throw "PowerPoint 未生成有效 PDF：$($item.OutputPath)"
      }
      Write-Output "已打印：$($item.OutputPath)"
    } finally {
      if ($null -ne $presentation) { $presentation.Close() }
    }
  }
} finally {
  if ($null -ne $ppt) {
    $ppt.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
