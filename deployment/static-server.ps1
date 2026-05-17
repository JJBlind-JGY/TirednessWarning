param(
    [int]$Port = 5173,
    [string]$WebRoot = (Join-Path $PSScriptRoot "..\dist"),
    [string]$FaceTarget = "http://127.0.0.1:8081",
    [string]$ApiTarget = "http://127.0.0.1:8081",
    [string]$EegTarget = "http://127.0.0.1:5000"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Net.Http

$WebRoot = (Resolve-Path -LiteralPath $WebRoot).Path
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add(("http://127.0.0.1:{0}/" -f $Port))
$listener.Start()

Write-Host ("Front server listening on http://127.0.0.1:{0}/" -f $Port)
Write-Host ("Web root: {0}" -f $WebRoot)

function Get-ContentType {
    param([string]$Path)

    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    switch ($extension) {
        ".html" { return "text/html; charset=utf-8" }
        ".js" { return "application/javascript; charset=utf-8" }
        ".mjs" { return "application/javascript; charset=utf-8" }
        ".css" { return "text/css; charset=utf-8" }
        ".json" { return "application/json; charset=utf-8" }
        ".png" { return "image/png" }
        ".jpg" { return "image/jpeg" }
        ".jpeg" { return "image/jpeg" }
        ".gif" { return "image/gif" }
        ".svg" { return "image/svg+xml" }
        ".ico" { return "image/x-icon" }
        ".woff" { return "font/woff" }
        ".woff2" { return "font/woff2" }
        default { return "application/octet-stream" }
    }
}

function Copy-RequestHeaders {
    param($Source, $Target)

    foreach ($key in $Source.Headers.AllKeys) {
        if ($key -match "^(Host|Connection|Content-Length|Transfer-Encoding|Expect|Proxy-Connection)$") {
            continue
        }
        try {
            $Target.Headers[$key] = $Source.Headers[$key]
        } catch {
            # Some restricted headers are managed by HttpWebRequest properties.
        }
    }
}

function Invoke-Proxy {
    param(
        $Context,
        [string]$TargetBase,
        [string]$Prefix,
        [bool]$StripPrefix
    )

    $request = $Context.Request
    $response = $Context.Response
    $pathAndQuery = $request.RawUrl
    if ($StripPrefix -and $pathAndQuery.StartsWith($Prefix)) {
        $pathAndQuery = $pathAndQuery.Substring($Prefix.Length)
        if (-not $pathAndQuery.StartsWith("/")) {
            $pathAndQuery = "/" + $pathAndQuery
        }
    }

    $targetUri = [Uri]::new($TargetBase.TrimEnd("/") + $pathAndQuery)
    $proxyRequest = [System.Net.HttpWebRequest]::CreateHttp($targetUri)
    $proxyRequest.Method = $request.HttpMethod
    $proxyRequest.AllowAutoRedirect = $false
    $proxyRequest.Timeout = 600000
    $proxyRequest.ReadWriteTimeout = 600000
    Copy-RequestHeaders -Source $request -Target $proxyRequest

    if ($request.HasEntityBody) {
        $proxyRequest.ContentType = $request.ContentType
        $proxyRequest.ContentLength = $request.ContentLength64
        $targetStream = $proxyRequest.GetRequestStream()
        try {
            $request.InputStream.CopyTo($targetStream)
        } finally {
            $targetStream.Close()
        }
    }

    try {
        $proxyResponse = $proxyRequest.GetResponse()
    } catch [System.Net.WebException] {
        if ($_.Exception.Response) {
            $proxyResponse = $_.Exception.Response
        } else {
            $body = [System.Text.Encoding]::UTF8.GetBytes(("Proxy target unavailable: {0}" -f $targetUri))
            $response.StatusCode = 502
            $response.ContentType = "text/plain; charset=utf-8"
            $response.ContentLength64 = $body.Length
            $response.OutputStream.Write($body, 0, $body.Length)
            return
        }
    }

    $sourceStream = $null
    try {
        $response.StatusCode = [int]$proxyResponse.StatusCode
        $response.ContentType = $proxyResponse.ContentType
        foreach ($key in $proxyResponse.Headers.AllKeys) {
            if ($key -match "^(Content-Length|Transfer-Encoding|Connection|Keep-Alive)$") {
                continue
            }
            try {
                $response.Headers[$key] = $proxyResponse.Headers[$key]
            } catch {
                # Ignore headers HttpListener owns.
            }
        }

        $sourceStream = $proxyResponse.GetResponseStream()
        if ($sourceStream) {
            $sourceStream.CopyTo($response.OutputStream)
        }
    } finally {
        if ($sourceStream) {
            $sourceStream.Close()
        }
        $proxyResponse.Close()
    }
}

function Send-StaticFile {
    param($Context)

    $request = $Context.Request
    $response = $Context.Response
    $relative = [Uri]::UnescapeDataString($request.Url.AbsolutePath.TrimStart("/"))
    if ([string]::IsNullOrWhiteSpace($relative)) {
        $relative = "index.html"
    }

    $candidate = Join-Path $WebRoot $relative
    $fullPath = [System.IO.Path]::GetFullPath($candidate)
    $rootPath = [System.IO.Path]::GetFullPath($WebRoot)
    if (-not $fullPath.StartsWith($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $response.StatusCode = 403
        return
    }

    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        $fullPath = Join-Path $WebRoot "index.html"
    }

    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        $body = [System.Text.Encoding]::UTF8.GetBytes("index.html not found")
        $response.StatusCode = 404
        $response.ContentType = "text/plain; charset=utf-8"
        $response.ContentLength64 = $body.Length
        $response.OutputStream.Write($body, 0, $body.Length)
        return
    }

    $bytes = [System.IO.File]::ReadAllBytes($fullPath)
    $response.StatusCode = 200
    $response.ContentType = Get-ContentType -Path $fullPath
    $response.ContentLength64 = $bytes.Length
    $response.OutputStream.Write($bytes, 0, $bytes.Length)
}

while ($listener.IsListening) {
    $context = $listener.GetContext()
    try {
        $path = $context.Request.Url.AbsolutePath
        if ($path.StartsWith("/face-api/")) {
            Invoke-Proxy -Context $context -TargetBase $FaceTarget -Prefix "/face-api" -StripPrefix $true
        } elseif ($path.StartsWith("/api/")) {
            Invoke-Proxy -Context $context -TargetBase $ApiTarget -Prefix "/api" -StripPrefix $true
        } elseif ($path.StartsWith("/eeg/")) {
            Invoke-Proxy -Context $context -TargetBase $EegTarget -Prefix "/eeg" -StripPrefix $false
        } elseif ($path.StartsWith("/wss")) {
            Invoke-Proxy -Context $context -TargetBase $FaceTarget -Prefix "/wss" -StripPrefix $false
        } else {
            Send-StaticFile -Context $context
        }
    } catch {
        $body = [System.Text.Encoding]::UTF8.GetBytes($_.Exception.Message)
        $context.Response.StatusCode = 500
        $context.Response.ContentType = "text/plain; charset=utf-8"
        $context.Response.ContentLength64 = $body.Length
        $context.Response.OutputStream.Write($body, 0, $body.Length)
    } finally {
        $context.Response.OutputStream.Close()
    }
}
