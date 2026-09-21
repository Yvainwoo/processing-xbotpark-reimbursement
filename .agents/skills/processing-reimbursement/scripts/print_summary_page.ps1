param(
  [Parameter(Mandatory = $true)][string]$TemplatePptx,
  [Parameter(Mandatory = $true)][string]$WorkPptx,
  [Parameter(Mandatory = $true)][string]$OutputPdf,
  [Parameter(Mandatory = $true)][string]$Category,
  [Parameter(Mandatory = $true)][string]$Amount,
  [string]$ProjectName = '儿童手工',
  [ValidateRange(1, 60)][int]$WaitSeconds = 20
)

$templatePath = (Resolve-Path -LiteralPath $TemplatePptx).Path
$workPath = [System.IO.Path]::GetFullPath($WorkPptx)
$outputPath = [System.IO.Path]::GetFullPath($OutputPdf)
if (Test-Path -LiteralPath $workPath) { throw "拒绝覆盖已有工作 PPTX：$workPath" }
if (Test-Path -LiteralPath $outputPath) { throw "拒绝覆盖已有 PDF：$outputPath" }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $workPath) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputPath) | Out-Null
Copy-Item -LiteralPath $templatePath -Destination $workPath

$ppt = $null
$presentation = $null
try {
  # 仅在幻灯片 XML 中替换模板已有的两段文字。这样可逐字保留所有运行属性、
  # 字号、字体、下划线、位置和文本框；PowerPoint 随后只读打开并打印，不保存。
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $archive = [System.IO.Compression.ZipFile]::Open($workPath, [System.IO.Compression.ZipArchiveMode]::Update)
  try {
    $entry = $archive.GetEntry('ppt/slides/slide1.xml')
    if ($null -eq $entry) { throw '模板缺少 ppt/slides/slide1.xml' }
    $reader = [System.IO.StreamReader]::new($entry.Open(), [System.Text.UTF8Encoding]::new($false), $true)
    try { $slideXml = $reader.ReadToEnd() } finally { $reader.Dispose() }
    $replacementProject = "$ProjectName（$Category）"
    $projectHits = ([regex]::Matches($slideXml, [regex]::Escape($ProjectName))).Count
    $amountHits = ([regex]::Matches($slideXml, [regex]::Escape('XXX'))).Count
    if ($projectHits -ne 1 -or $amountHits -ne 1) {
      throw "模板字段替换数量异常：项目名称 $projectHits 次，金额 $amountHits 次"
    }
    $updatedXml = $slideXml.Replace($ProjectName, $replacementProject).Replace('XXX', $Amount)
    $entry.Delete()
    $newEntry = $archive.CreateEntry('ppt/slides/slide1.xml', [System.IO.Compression.CompressionLevel]::Optimal)
    $writer = [System.IO.StreamWriter]::new($newEntry.Open(), [System.Text.UTF8Encoding]::new($false))
    try { $writer.Write($updatedXml) } finally { $writer.Dispose() }
  } finally {
    $archive.Dispose()
  }

  $ppt = New-Object -ComObject PowerPoint.Application
  $ppt.DisplayAlerts = 1
  # PowerPoint 的 ActivePrinter 在此环境里是只读空值；因此以 Windows 默认打印机
  # 验证实际打印目标。PrintOut 未指定打印机时会使用这个默认值。
  $defaultPrinter = Get-CimInstance Win32_Printer | Where-Object { $_.Default } | Select-Object -First 1
  if ($null -eq $defaultPrinter -or $defaultPrinter.Name -ne 'Microsoft Print to PDF') {
    $actualName = if ($null -eq $defaultPrinter) { '<无默认打印机>' } else { [string]$defaultPrinter.Name }
    throw "当前 Windows 默认打印机不是 Microsoft Print to PDF：$actualName"
  }
  $presentation = $ppt.Presentations.Open($workPath, $true, $false, $false)
  # 使用已选定的 Microsoft Print to PDF 及其 A4 默认纸张；不是“另存为 PDF”。
  $presentation.PrintOptions.OutputType = 1
  $presentation.PrintOptions.FitToPage = -1
  $presentation.PrintOptions.FrameSlides = 0
  $presentation.PrintOptions.PrintInBackground = 0
  $presentation.PrintOut(1, 1, $outputPath, 1, 0)
  $deadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
  while ((-not (Test-Path -LiteralPath $outputPath) -or (Get-Item -LiteralPath $outputPath).Length -eq 0) -and [DateTime]::UtcNow -lt $deadline) {
    Start-Sleep -Milliseconds 500
  }
  if (-not (Test-Path -LiteralPath $outputPath) -or (Get-Item -LiteralPath $outputPath).Length -eq 0) {
    throw 'PowerPoint 打印流程未生成有效 PDF'
  }
} finally {
  if ($null -ne $presentation) { $presentation.Close() }
  if ($null -ne $ppt) {
    $ppt.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
