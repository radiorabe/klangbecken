set("log.file", false)
#set("log.file.path","/tmp/<script>.log")
set("log.stdout", false)
set("server.telnet", false)
set("server.telnet.port", 1234)
set("log.level", 3)

set("log.syslog", true)
# set("log.syslog.facility","DAEMON")
# set("log.syslog.program","liquidsoap")
# set("log.unix_timestamps",false)

set("server.socket", true)
#set("server.socket.path","<sysrundir>/<script>.sock")
#set("server.socket.permissions",384)
#set("server.timeout",30.)

#set("init.daemon.pidfile",true)
#set("init.daemon.pidfile.path","<sysrundir>/<script>.pid")

#set("harbor.bind_addr","0.0.0.0")
#set("harbor.max_connections",2)
#set("harbor.reverse_dns",true)

data_dir = getenv("KLANGBECKEN_DATA")
if not file.is_directory(data_dir) then
    log(level=2, "ERROR: Cannot find data directory: " ^ data_dir)
    shutdown()
end

jingles = playlist(id="jingles", mode="randomize", reload_mode="watch", path.concat(data_dir, "jingles.m3u"))
music = playlist(id="music", mode="randomize", reload_mode="watch",  path.concat(data_dir, "music.m3u"))

insert_jingle = ref false
restart = ref true

restart_delay = interactive.float("restart.delay", 1.0)
restart_fade = interactive.float("restart.fade", 3.0)

def jingle_timeout() =
  jingle_times = [5m0s, 20m0s, 35m0s, 50m0s]
  if list.fold(fun (a,b) -> a or b, false, jingle_times) then
    print('Jingle up next')
    insert_jingle := true
  end
  1.0
end
add_timeout(0.0, jingle_timeout)

def check_jingle() =
  if (!insert_jingle) then
    insert_jingle := false
    true
  else
    false
  end
end

radio = switch(id="radio", [
  (check_jingle, jingles),
  ({true}, music),
])

def restart_fun(_) =
  log("Restarting Klangbecken")
  restart := true
  source.skip(radio)
  "Klangbecken restarted"
end


server.register(namespace='klangbecken',
                description="Restart Klangbecken with a fade in",
                usage="restart",
                "restart", restart_fun)


def trans(old, new) =
  if !restart and source.id(new) == "radio" then
    restart := false
    sequence([blank(duration=restart_delay()),
              fade.initial(duration=restart_fade(), new)])
  else
    new
  end
end

radio = fallback(track_sensitive=false,
                 transitions=[trans],
                 [radio, blank(id="blank")])


output.icecast(
  %mp3(bitrate=128),
  mount="/rabe-128.mp3",
  description="Radio Bern RaBe 95.6",
  url="http://www.rabe.ch/",
  host="localhost", port=8000, password="hackme",
  radio)
