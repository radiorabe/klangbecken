# ================================================= #
# SETTINGS                                          #
#                                                   #
# Environment Variables:                            #
#   - KLANGBECKEN_ALSA_DEVICE                       #
#     ALSA device to send sound to                  #
#     Default: default                              #
#                                                   #
#   - KLANGBECKEN_DATA_DIR                          #
#     Directory with data                           #
#     Default: ./data                               #
#                                                   #
#   - KLANGBECKEN_COMMAND                           #
#     Klangbecken command                           #
#     Default: python -m klangbecken                #
#                                                   #
#   - KLANGBECKEN_PLAYER_SOCKET                     #
#     Path to socket to listen on                   #
#     Default: klangbecken.sock                      #
# ================================================= #

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
set("server.socket.path", getenv_fallback("KLANGBECKEN_PLAYER_SOCKET", "./klangbecken.sock"))
set("server.socket.permissions", 0o660)  # Make socket group readable/writable

# Get the Klangbecken data directory
DATA_DIR = getenv_fallback("KLANGBECKEN_DATA_DIR", "./data")
if not file.is_directory(DATA_DIR) then
    log(level=2, "ERROR: Cannot find data directory: " ^ DATA_DIR)
    shutdown()
end

# Get the klangbecken command
KLANGBECKEN_COMMAND = getenv_fallback("KLANGBECKEN_COMMAND", "python -m klangbecken")

# Get the alsa device
ALSA_DEVICE = getenv_fallback("KLANGBECKEN_ALSA_DEVICE", "default")

# ================================================= #
# PLAYLISTS                                         #
# ================================================= #

# calculate waiting time for repeating a track depending on its playlist
def calc_wait(playlist) =
  if playlist == "music" then 259200.0 # 3 days
  elsif playlist == "classics" then 86400.0 # 1 day
  elsif playlist == "jingles" then 3600.0 # 1 hour
  else 0.0 end
end

# check if track was played recently
skipped = ref 0
def check_next_func(r) =
  metadata = request.metadata(r)
  filename = request.filename(r)

  last_play = float_of_string(metadata["last_play_epoch"])
  if filename == "" then
    false
  elsif last_play == 0.0 then
    skipped := 0
    log("track was never played before: #{filename}", label="check_next_func")
    true
  else
    diff = gettimeofday() - last_play
    playlist = metadata["source"]
    if diff < calc_wait(playlist) then
      skipped := !skipped + 1
      log("track was recently played: #{filename} (#{diff} seconds ago)", label="check_next_func")
      if !skipped >= 10 then
        skipped := 0
        log("too many skipped tracks, playing #{filename} anyway", label="check_next_func")
        true
      else
        false
      end
    else
      skipped := 0
      log("next: #{filename} (track was last played #{diff} seconds ago)", label="check_next_func")
      true
    end
  end
end

# Priority queue
queue = request.equeue(id="queue", length=5.0)
# Convert mono queue entries (jingles) to stereo
queue = audio_to_stereo(queue)
# Cut silence at start and end
queue = cue_cut(queue, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Music playlist
music = playlist(
  path.concat(DATA_DIR, "music.m3u"),
  id="music",
  mode="random",
  reload_mode="watch",
  check_next=check_next_func,
)
# Cut silence at start and end
music = cue_cut(music, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Classics playlist
classics = playlist(
  path.concat(DATA_DIR, "classics.m3u"),
  id="classics",
  mode="random",
  reload_mode="watch",
  check_next=check_next_func,
)
# Cut silence at start and end
classics = cue_cut(classics, cue_in_metadata="cue_in", cue_out_metadata="cue_out")

# Jingles playlist
jingles = playlist(
  path.concat(DATA_DIR, "jingles.m3u"),
  id="jingles",
  mode="random",
  reload_mode="watch",
  check_next=check_next_func,
)
# Convert mono jingles to stereo
jingles = audio_to_stereo(jingles)
# Cut silence at start and end
jingles = cue_cut(jingles, cue_in_metadata="cue_in", cue_out_metadata="cue_out")


# ================================================= #
# MIX MUSIC AND CLASSICS                            #
# ================================================= #

music = random(weights=[5, 1], [music, classics])


# ================================================= #
# INSERT JINGLE AND QUEUE TRACKS WHEN NEEDED        #
# ================================================= #

insert_jingle = ref false
on_air = ref false

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
  ({!on_air}, queue),
  ({true}, music),
])

def on_track_func(m) =
  # Reset jingle playing flag
  if m['source'] == 'jingles' then
    insert_jingle := false
  end
end
radio = on_track(on_track_func, radio)


# ================================================= #
# REGISTER EXTERNAL RESTART COMMAND                 #
# ================================================= #

restart = ref true

def on_air_func(state) =
  state = string.case(state)
  state = string.trim(state)
  if state == "" then
    # Return state
    "#{!on_air}"
  else
    on_air := bool_of_string(state)
    if !on_air then
      log("Starting Klangbecken")
      restart := true
      source.skip(radio)
      "Klangbecken started"
    else
      log("Stopping Klangbecken")
      "Klangbecken stopped"
    end
  end
end

server.register(namespace='klangbecken',
                description="Control, if the player is on air. Returns the current state, if called without argument.",
                usage="onair [true|false]",
                "onair",
                on_air_func)
server.register(
  "on_air",
  on_air_func,
  usage="on_air [true|false]",
  description="Control if the player is on air. Returns the current state, if called without argument."
)

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
  log('Playing: #{m["filename"]}', label="log_metadata_func")

  if m['filename'] == '' then
    log("WARNING: Empty filename", label="log_metadata_func")
  end

  if !on_air then
    # Prepare play logger
    have_new_metadata := true
    filename := m['filename']
  end
end
radio = on_track(log_metadata_func, radio)

def run_play_logger() =
  have_new_metadata := false
  log("#{KLANGBECKEN_COMMAND} playlog -d #{DATA_DIR} #{!filename}", label="run_play_logger")

  system("#{KLANGBECKEN_COMMAND} playlog -d #{DATA_DIR} #{!filename}")
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

output.alsa(id="out", device=ALSA_DEVICE, radio)
