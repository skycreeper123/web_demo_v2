using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Windows.Forms;

internal static class Program
{
    private const string AppUrl = "http://127.0.0.1:8000/";

    [STAThread]
    private static int Main()
    {
        string baseDir = AppContext.BaseDirectory;
        string backendMain = Path.Combine(baseDir, "backend", "app", "main.py");
        string venvPython = Path.Combine(baseDir, ".venv", "Scripts", "python.exe");

        if (!File.Exists(backendMain))
        {
            ShowError(
                "Missing backend entry",
                "Could not find backend/app/main.py next to this launcher."
            );
            return 1;
        }

        if (IsServerReady())
        {
            OpenBrowser();
            return 0;
        }

        if (!TryStartServer(baseDir, backendMain, venvPython))
        {
            ShowError(
                "Unable to start backend",
                "Tried .venv Python and system Python, but neither could start the server."
            );
            return 1;
        }

        if (!WaitForServerReady())
        {
            ShowError(
                "Server start timed out",
                "The backend process was started, but http://127.0.0.1:8000 did not respond in time."
            );
            return 1;
        }

        OpenBrowser();
        return 0;
    }

    private static bool TryStartServer(string baseDir, string backendMain, string venvPython)
    {
        if (File.Exists(venvPython) && TryStartPython(venvPython, Quote(backendMain), baseDir))
        {
            return true;
        }

        if (TryStartPython("python", Quote(backendMain), baseDir))
        {
            return true;
        }

        return TryStartPython("py", "-3 " + Quote(backendMain), baseDir);
    }

    private static bool TryStartPython(string fileName, string arguments, string workingDirectory)
    {
        try
        {
            ProcessStartInfo startInfo = new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            };

            using (Process process = Process.Start(startInfo))
            {
                return process != null;
            }
        }
        catch
        {
            return false;
        }
    }

    private static bool WaitForServerReady()
    {
        const int maxAttempts = 40;
        for (int attempt = 0; attempt < maxAttempts; attempt++)
        {
            if (IsServerReady())
            {
                return true;
            }

            Thread.Sleep(500);
        }

        return false;
    }

    private static bool IsServerReady()
    {
        try
        {
            using (HttpClient client = new HttpClient())
            {
                client.Timeout = TimeSpan.FromSeconds(2);
                using (HttpResponseMessage response = client.GetAsync(AppUrl).GetAwaiter().GetResult())
                {
                    return response.IsSuccessStatusCode;
                }
            }
        }
        catch
        {
            return false;
        }
    }

    private static void OpenBrowser()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = AppUrl,
            UseShellExecute = true,
        });
    }

    private static void ShowError(string title, string message)
    {
        MessageBox.Show(
            message,
            title,
            MessageBoxButtons.OK,
            MessageBoxIcon.Error
        );
    }

    private static string Quote(string value)
    {
        return "\"" + value + "\"";
    }
}
