# --- History Settings ---
HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
setopt appendhistory
setopt sharehistory
setopt hist_ignore_dups
setopt hist_expire_dups_first

# --- Completion Settings ---
autoload -U compinit
compinit
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'

# --- Colors ---
export CLICOLOR=1
ls --color -d . >/dev/null 2>&1 && alias ls='ls --color=auto' || alias ls='ls -G'

# --- Prompt ---
# Shows current folder in cyan and ends with %
PROMPT='%F{cyan}%~%f %# '

# --- Useful Aliases ---
alias ll='ls -la'
alias la='ls -A'
alias l='ls -CF'
alias cls='clear'
