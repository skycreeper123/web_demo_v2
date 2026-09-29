using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

internal static class Program
{
    private const string AppUrl = "http://127.0.0.1:8000/";
    private static readonly object LogLock = new object();
    private static StreamWriter log;
    private static Process backend;
    private static bool noPause;
    private static bool noBrowser;
    private static readonly ConsoleControlHandler ControlHandler = OnConsoleControl;
    private delegate bool ConsoleControlHandler(uint controlType);
    [DllImport("Kernel32.dll")]
    private static extern bool SetConsoleCtrlHandler(ConsoleControlHandler handler, bool add);

    [STAThread]
    private static int Main(string[] args)
    {
        noPause = Array.IndexOf(args, "--no-pause") >= 0;
        noBrowser = Array.IndexOf(args, "--no-browser") >= 0;
        Console.OutputEncoding = new UTF8Encoding(false);
        SetConsoleCtrlHandler(ControlHandler, true);
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string logPath = Path.Combine(baseDir, "logs", "launcher.log");
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(logPath));
            log = new StreamWriter(new FileStream(logPath, FileMode.Append, FileAccess.Write,
                FileShare.ReadWrite), new UTF8Encoding(false));
            log.AutoFlush = true;
            Write("=== Prompt Tool launcher " + DateTime.Now.ToString("s") + " ===");
            Write("Project: " + baseDir);
            Write("Startup log: " + logPath);
            Write("URL: " + AppUrl);
            string backendMain = Path.Combine(baseDir, "backend", "app", "main.py");
            if (!File.Exists(backendMain) || !File.Exists(Path.Combine(baseDir, "frontend", "index.html")))
                return Fail("Missing backend/app/main.py or frontend/index.html. Keep the EXE in the project folder.");
            if (IsServerReady())
            {
                Write("Prompt Tool is already running.");
                OpenBrowser();
                return 0;
            }
            if (IsPortOccupied())
                return Fail("Port 8000 is occupied, but the Prompt Tool health check failed. Close the old server or the application using that port, then retry.");

            string[] candidates = { Path.Combine(baseDir, ".venv", "Scripts", "python.exe"), "python", "py" };
            foreach (string candidate in candidates)
            {
                string prefix = candidate == "py" ? "-3 " : "";
                if (!CheckPython(candidate, prefix, baseDir)) continue;
                Write("Starting backend with: " + candidate);
                backend = StartPython(candidate, prefix + "-X utf8 -u " + Quote(backendMain), baseDir);
                Stopwatch timer = Stopwatch.StartNew();
                bool ready = false;
                while (timer.Elapsed < TimeSpan.FromSeconds(40))
                {
                    if (backend.HasExited)
                    {
                        backend.WaitForExit(); // Drain traceback before reporting failure.
                        return Fail("Backend exited during startup (exit code " + backend.ExitCode + "). See the error above and logs/launcher.log.");
                    }
                    if (IsServerReady()) { ready = true; break; }
                    Thread.Sleep(250);
                }
                if (!ready)
                {
                    StopBackend();
                    return Fail("Backend did not become ready within 40 seconds. See logs/launcher.log.");
                }
                Write("Ready: " + AppUrl);
                Write("Keep this log window open. Closing it or pressing Ctrl+C stops the backend.");
                OpenBrowser();
                backend.WaitForExit();
                int exitCode = backend.ExitCode;
                Write("Backend stopped (exit code " + exitCode + ").");
                return exitCode == 0 ? 0 : Fail("Backend stopped unexpectedly. See logs/launcher.log.");
            }
            return Fail("No usable Python 3.10+ found. Repair .venv or install Python with sqlite3 and SSL support, then retry. See the interpreter errors above.");
        }
        catch (Exception ex)
        {
            StopBackend();
            return Fail(ex.ToString());
        }
        finally
        {
            lock (LogLock)
            {
                if (log != null) log.Dispose();
                log = null;
            }
            if (backend != null) backend.Dispose();
        }
    }

    private static bool CheckPython(string fileName, string prefix, string baseDir)
    {
        Write("Checking Python: " + fileName);
        try
        {
            // Broken/moved virtual environments can create a process then exit immediately.
            string code = "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'; import sqlite3, ssl; print(sys.executable); print(sys.version)";
            using (Process process = StartPython(fileName, prefix + "-X utf8 -u -c " + Quote(code), baseDir))
            {
                if (!process.WaitForExit(10000))
                {
                    process.Kill();
                    process.WaitForExit();
                    Write("Python check timed out; trying the next interpreter.");
                    return false;
                }
                process.WaitForExit();
                if (process.ExitCode == 0) return true;
                Write("Python check failed (exit code " + process.ExitCode + "); trying the next interpreter.");
            }
        }
        catch (Exception ex) { Write("Python unavailable: " + ex.Message); }
        return false;
    }

    private static Process StartPython(string fileName, string arguments, string baseDir)
    {
        ProcessStartInfo info = new ProcessStartInfo
        {
            FileName = fileName, Arguments = arguments, WorkingDirectory = baseDir,
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
        };
        Process process = new Process { StartInfo = info };
        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Write(e.Data); };
        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Write(e.Data); };
        try
        {
            process.Start();
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            return process;
        }
        catch { process.Dispose(); throw; }
    }

    private static bool IsServerReady()
    {
        try
        {
            // Loopback requests must bypass system HTTP proxies.
            using (HttpClientHandler handler = new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false })
            using (HttpClient client = new HttpClient(handler))
            {
                client.Timeout = TimeSpan.FromSeconds(1);
                using (HttpResponseMessage response = client.GetAsync(AppUrl + "api/health").GetAwaiter().GetResult())
                    return response.IsSuccessStatusCode && response.Content.ReadAsStringAsync().GetAwaiter().GetResult().Trim() == "prompt-tool-ready";
            }
        }
        catch { return false; }
    }

    private static bool IsPortOccupied()
    {
        try
        {
            using (TcpClient client = new TcpClient())
            {
                var task = client.ConnectAsync("127.0.0.1", 8000);
                return task.Wait(1000) && client.Connected;
            }
        }
        catch { return false; }
    }

    private static void OpenBrowser()
    {
        if (noBrowser) return;
        try { Process.Start(new ProcessStartInfo { FileName = AppUrl, UseShellExecute = true }); }
        catch (Exception ex) { Write("Could not open the browser: " + ex.Message + ". Open " + AppUrl + " manually."); }
    }

    private static void StopBackend()
    {
        try
        {
            if (backend != null && !backend.HasExited)
            {
                backend.Kill();
                backend.WaitForExit(3000);
            }
        }
        catch (InvalidOperationException) { }
    }

    private static bool OnConsoleControl(uint controlType)
    {
        // Never stop a server merely opened by a second launcher.
        StopBackend();
        return false;
    }

    private static void Write(string message)
    {
        lock (LogLock)
        {
            Console.WriteLine(message);
            if (log != null)
            {
                try { log.WriteLine(message); }
                catch (IOException) { /* Keep console output if the disk fills up. */ }
            }
        }
    }

    private static int Fail(string message)
    {
        Write("ERROR: " + message);
        if (!noPause && !Console.IsInputRedirected)
        {
            Write("Press Enter to close this window.");
            Console.ReadLine();
        }
        return 1;
    }

    private static string Quote(string value) { return "\"" + value + "\""; }
}
