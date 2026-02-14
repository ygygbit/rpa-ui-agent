Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$bounds = [Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save('C:\Users\guangyang\Documents\rpa\screen.png')
$graphics.Dispose()
$bitmap.Dispose()
Write-Host 'Screenshot saved'
