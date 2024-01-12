#! /bin/bash

mv ~/.zshrc ~/.zshrc.backup
ln -s ~/.config/zsh/.zshrc ~/.zshrc
mv ~/.p10k.zsh ~/.p10k.zsh.backup
ln -s ~/.config/zsh/.p10k.zsh ~/.p10k.zsh

echo "$ZSH_CUSTOM"
# would be nice to check if we need to do this
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git $ZSH_CUSTOM/plugins/zsh-syntax-highlighting
# echo "source ${PWD}/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" >> ${ZDOTDIR:-$HOME}/.zshrc
