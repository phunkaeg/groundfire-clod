using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

internal static class ExportSmokeAtlas
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string path);

    private static int Main(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("Usage: ExportSmokeAtlas.exe <CloD installation> <DDS output>");
            return 2;
        }
        try
        {
            string core = Path.Combine(Path.GetFullPath(args[0]), "parts", "core");
            if (!SetDllDirectory(core))
                throw new IOException("Could not set the game's DLL directory");
            AppDomain.CurrentDomain.AssemblyResolve += (sender, request) =>
            {
                string path = Path.Combine(core, new AssemblyName(request.Name).Name + ".dll");
                return File.Exists(path) ? Assembly.LoadFrom(path) : null;
            };
            Type sfs = Assembly.LoadFrom(Path.Combine(core, "core.dll")).GetType("maddox.rts.WSFS", true);
            var mount = (Func<string, bool>)Delegate.CreateDelegate(typeof(Func<string, bool>), sfs.GetMethod("MountSingle"));
            var open = (Func<string, int, long>)Delegate.CreateDelegate(typeof(Func<string, int, long>),
                sfs.GetMethod("open", new[] { typeof(string), typeof(int) }));
            var read = (Func<long, byte[], int, int, int>)Delegate.CreateDelegate(typeof(Func<long, byte[], int, int, int>),
                sfs.GetMethod("read"));
            var seek = (Func<long, long, int, long>)Delegate.CreateDelegate(typeof(Func<long, long, int, long>),
                sfs.GetMethod("lseek"));
            var close = (Func<long, bool>)Delegate.CreateDelegate(typeof(Func<long, bool>), sfs.GetMethod("close"));
            const string atlas = "3do/sfx/Res/Smoke_Sprites_Air_W.dds";
            foreach (string archive in new[] { "core_data.SFS", "core_data01.SFS" })
            {
                string path = Path.Combine(core, archive);
                if (!File.Exists(path) || !mount(path))
                    continue;
                long handle = open("parts/core/" + atlas, 0);
                if (handle < 0)
                    handle = open(atlas, 0);
                if (handle < 0)
                    continue;
                try
                {
                    long length = seek(handle, 0, 2);
                    if (length < 128 || length > 32000000 || seek(handle, 0, 0) != 0)
                        throw new IOException("Unexpected atlas length");
                    byte[] bytes = new byte[(int)length];
                    for (int position = 0; position < bytes.Length;)
                    {
                        int count = read(handle, bytes, position, bytes.Length - position);
                        if (count <= 0)
                            throw new IOException("Short atlas read");
                        position += count;
                    }
                    if (bytes[0] != 'D' || bytes[1] != 'D' || bytes[2] != 'S' || bytes[3] != ' ')
                        throw new IOException("The exported texture is not DDS");
                    File.WriteAllBytes(args[1], bytes);
                    Console.WriteLine("Read " + length + " atlas bytes from " + archive);
                    return 0;
                }
                finally
                {
                    close(handle);
                }
            }
            throw new FileNotFoundException(atlas);
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.GetBaseException().Message);
            return 1;
        }
    }
}
