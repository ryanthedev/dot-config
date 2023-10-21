ln -s ~/.config/zsh/.zshrc ~/.zshrc

# wouuld be nice to check if we need to do this
git clone https://github.com/zsh-users/zsh-syntax-highlighting.git
echo "source ${(q-)PWD}/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" >> ${ZDOTDIR:-$HOME}/.zshrc