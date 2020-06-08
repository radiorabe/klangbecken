# ================================================= #
# SETTINGS                                          #
#                                                   #
# Environment Variables:                            #
#   - KLANGBECKEN_ALSA_DEVICE                       #
#     ALSA device to send sound to                  #
#   - KLANGBECKEN_DATA                              #
#     Directory with data                           #
#   - KLANGBECKEN_PATH                              #
#     Path to klangbecken.py                        #
#   - KLANGBECKEN_SOCKET_PATH                       #
#     Path to socket to listen on                   #
# ================================================= #

# set setting to getenv(var) if set
def set_if_env(setting, var) =
  if getenv(var) != "" then
    set(setting, getenv(var))
  end
end

# return value of environment variable if set, otherwise fallback
def getenv_fallback(var, fallback) =
  if getenv(var) != "" then
    getenv(var)
  else
    fallback
  end
end

# log file
set("log.file", false)
set("log.stdout", true)
set("server.telnet", false)
set("server.telnet.port", 1234)
set("log.level", 3)

# socket
set("server.socket", true)
set_if_env("server.socket.path", "KLANGBECKEN_SOCKET_PATH")

# Get the Klangbecken data directory
DATA_DIR = getenv_fallback("KLANGBECKEN_DATA", "data")
if not is_directory(DATA_DIR) then
    log(level=2, "ERROR: Cannot find data directory: " ^ DATA_DIR)
    shutdown()
end

# Get the klangecken command
CMD_PATH = getenv_fallback("KLANGBECKEN_PATH", "./klangbecken.py")

# Get the alsa device
ALSA_DEVICE = getenv_fallback("KLANGBECKEN_ALSA_DEVICE", "default")

# ================================================= #
# PLAYLISTS                                         #
# ================================================= #

# parse index.json and keep it up to date
index = ref []
index_filename = path.concat(DATA_DIR, "index.json")
index_last_update = ref 0.0
def read_index() =
  diff = gettimeofday() - !index_last_update
  if diff > 1. then
    log("updating index", label="update_index")
    index := of_json(default=[("list", [("key", "value")])], file.contents(index_filename))
    index_last_update := gettimeofday()
  end
end
if file.exists(index_filename) then read_index() end
file.watch(index_filename, read_index)

# calculate waiting time for repeating a track depending on its playlist
def calc_wait(playlist) =
  if playlist == "music" then 259200 # 3 days
  elsif playlist == "classics" then 86400 # 1 day
  elsif playlist == "jingles" then 3600 # 1 hour
  else 0 end
end

# check if track was played recently
skipped = ref 0
def check_next_func(r) = 
  # get id from filename
  id = basename(request.filename(r))
  id = string.replace(pattern="\..*", fun(_) -> "", id)
  # get info about track in index
  meta = list.assoc(default=[], id, !index)
  # get last_play as a unix timestamp
  last_play = meta["last_play"]

  if string.length(last_play) == 0 then
    log("track was never played before: #{request.filename(r)}", label="check_next_func")
    true
  else
    last_play_unix = int_of_string(string.trim(get_process_output("date --date=#{last_play} +%s")))
    now_unix = int_of_float(gettimeofday())
    diff = now_unix - last_play_unix
    if diff < calc_wait(meta["playlist"]) then
      skipped := !skipped + 1
      log("track was recently played: #{request.filename(r)} (#{diff} seconds ago)", label="check_next_func")
      if !skipped >= 10 then
        skipped := 0
        log("too many skipped tracks, playing #{request.filename(r)} anyway", label="check_next_func")
        true
      else
        false
      end
    else
      log("next: #{request.filename(r)} (track was last played #{diff} seconds ago)", label="check_next_func")
      true
    end
  end
end

# Priority playlist for 'play next' feature
prio = playlist.once(id="prio", reload_mode="watch", path.concat(DATA_DIR, "prio.m3u"))
# Cut silence at start and end
prio = cue_cut(prio, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Music playlist
music = playlist(id="music", mode="randomize", reload_mode="watch",
                 check_next=check_next_func, path.concat(DATA_DIR, "music.m3u"))
# Cut silence at start and end
music = cue_cut(music, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Classics playlist
classics = playlist(id="classics", mode="randomize", reload_mode="watch",
                    check_next=check_next_func, path.concat(DATA_DIR, "classics.m3u"))
# Cut silence at start and end
classics = cue_cut(classics, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Jingles playlist
jingles = playlist(id="jingles", mode="randomize", reload_mode="watch",
                   check_next=check_next_func, path.concat(DATA_DIR, "jingles.m3u"))
# Convert mono jingles to stereo
jingles = audio_to_stereo(jingles)
# Cut silence at start and end
jingles = cue_cut(jingles, cue_in_metadata="cue_in", cue_out_metadata="cue_out")


# ================================================= #
# MIX MUSIC AND CASSICS                             #
# ================================================= #

music = random(weights=[5, 1], [music, classics])


# ================================================= #
# PLAY FROM PRIORITY PLAYLIST IF AVAILABLE          #
# ================================================= #

music = fallback([prio, music])


# ================================================= #
# INSERT JINGLE EVERY 15 MINUTES                    #
# ================================================= #

insert_jingle = ref false

def jingle_timeout() =
  jingle_times = [5m0s, 20m0s, 35m0s, 50m0s]
  if list.fold(fun (a,b) -> a or b, false, jingle_times) then
    log('Jingle up next')
    insert_jingle := true
  end
  1.0
end
add_timeout(0.0, jingle_timeout)

radio = switch(id="radio", [
  ({!insert_jingle}, jingles),
  ({true}, music),
])


def on_track_func(m) =
  # Reset jingle playing flag
  insert_jingle := false

  # Clear prio playlist
  system("echo > #{DATA_DIR}/prio.m3u")
end
radio = on_track(on_track_func, radio)


# ================================================= #
# REGISTER EXTERNAL RESTART COMMAND                 #
# ================================================= #

restart = ref true
onair = ref false

def onair_func(state) =
  onair := bool_of_string(string.case(state))
  if !onair then
    log("Starting Klangbecken")
    restart := true
    source.skip(radio)
    "Klangbecken started"
  else
    log("Stopping Klangbecken")
    system("#{CMD_PATH} playlog -d #{DATA_DIR} --off")
    "Klangbecken stopped"
  end
end

server.register(namespace='klangbecken',
                description="Control, if the player is on air",
                usage="onair (true|false)",
                "onair",
                onair_func)

# Have restart delay and fade dynamically reconfigurable
# for debugging purpose
restart_delay = interactive.float("restart.delay", 1.0)
restart_fade = interactive.float("restart.fade", 1.0)

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


# ================================================= #
# LOGGING METADATA                                  #
# ================================================= #

have_new_metadata = ref false
filename = ref ''

def log_metadata_func(m) =
  # Log to stdout
  print('Playing: ', newline=false)
  print(m['filename'])

  if !onair then
    # Prepare play logger
    have_new_metadata := true
    filename := m['filename']
  end
end
radio = on_track(log_metadata_func, radio)

def run_play_logger() =
  have_new_metadata := false
  system("#{CMD_PATH} playlog -d #{DATA_DIR} #{!filename}")
end

# Run the logging command in the background, not to lock up the player
exec_at(pred=fun() -> !have_new_metadata, run_play_logger)


# ================================================= #
# AUDIO PROCESSING                                  #
# ================================================= #

# Apply calculated replay gain
radio = amplify(1., override="replaygain_track_gain", radio)
# Moderate cross-fading
radio = crossfade(start_next=.5, fade_out=1., fade_in=0., radio)


# ================================================= #
# OUTPUT                                            #
# ================================================= #

output.alsa(id="out", bufferize=false, device=ALSA_DEVICE, radio)
