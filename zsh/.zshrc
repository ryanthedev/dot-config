# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:/usr/local/bin:$PATH

# Path to your oh-my-zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time oh-my-zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="powerlevel10k/powerlevel10k"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment the following line to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment the following line to automatically update without prompting.
# DISABLE_UPDATE_PROMPT="true"

# Uncomment the following line to change how often to auto-update (in days).
# export UPDATE_ZSH_DAYS=13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS="true"

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# Caution: this setting can cause issues with multiline prompts (zsh 5.7.1 and newer seem to work)
# See https://github.com/ohmyzsh/ohmyzsh/issues/5765
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder
export ZSH_CUSTOM=$HOME/.oh-my-zsh/custom
# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(
  git
  zsh-syntax-highlighting
  vi-mode
  kubectl
)
source $ZSH/oh-my-zsh.sh

# User configuration
typeset -U PATH  # Remove duplicate PATH entries

# Core paths
export PATH=$PATH:/opt/homebrew/bin
export PATH=$PATH:$HOME/.local/bin

# Language runtimes (conditional - only if installed)
[ -d /usr/local/go/bin ] && export PATH=$PATH:/usr/local/go/bin
[ -d $HOME/.dotnet ] && export DOTNET_ROOT=$HOME/.dotnet && export PATH=$PATH:$DOTNET_ROOT:$DOTNET_ROOT/tools
[ -d $HOME/.nvim/bin ] && export PATH=$PATH:$HOME/.nvim/bin

# App-specific paths (conditional)
[ -d /Applications/kitty.app ] && export PATH=$PATH:/Applications/kitty.app/Contents/MacOS

# tmux
export TMUX_CONF=~/.config/tmux/tmux.conf
[ -d $HOME/.config/tmux/plugins/tmux-session-wizard ] && export PATH=$HOME/.config/tmux/plugins/tmux-session-wizard/bin:$PATH



# NVM
export NVM_DIR="$([ -z "${XDG_CONFIG_HOME-}" ] && printf %s "${HOME}/.nvm" || printf %s "${XDG_CONFIG_HOME}/nvm")"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" --no-use  # Defer node version activation

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='mvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch x86_64"

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within the ZSH_CUSTOM folder.
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"
alias k=kubectl
alias vim=nvim
alias p=python3
alias python=python3
alias pip=pip3
alias pp=pip3

# alias code='open -a "Visual Studio Code" --args --user-data-dir=$HOME/.config/vscode'


# VSCode shell integration
[[ "$TERM_PROGRAM" == "vscode" ]] && . "/Applications/Visual Studio Code.app/Contents/Resources/app/out/vs/workbench/contrib/terminal/common/scripts/shellIntegration-rc.zsh"

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh
if command -v zoxide >/dev/null 2>&1; then
  eval "$(zoxide init zsh 2>/dev/null)"
fi

unsetopt HUP  # Keep jobs running after exiting shell.
unsetopt CHECK_JOBS  # Don't report on jobs when shell exit.

# Tool activations (conditional - only if installed)
[ -x ~/.local/bin/mise ] && eval "$(~/.local/bin/mise activate 2>/dev/null)"
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh
[ -s ~/.luaver/luaver ] && source ~/.luaver/luaver
[ -s ~/.luaver/completions/luaver.bash ] && source ~/.luaver/completions/luaver.bash
[ -s "$NVM_DIR/bash_completion" ] && source "$NVM_DIR/bash_completion"

# Google Cloud SDK (conditional)
[ -f "$HOME/.gcloud/google-cloud-sdk/path.zsh.inc" ] && source "$HOME/.gcloud/google-cloud-sdk/path.zsh.inc"
[ -f "$HOME/.gcloud/google-cloud-sdk/completion.zsh.inc" ] && source "$HOME/.gcloud/google-cloud-sdk/completion.zsh.inc"

# Load local .env file if it exists
if [ -f $HOME/.config/zsh/.env ]; then
    set -a  # Automatically export all variables
    source $HOME/.config/zsh/.env
    set +a  # Stop auto-exporting
fi
