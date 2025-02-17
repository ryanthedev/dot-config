ln -sf "$HOME/.config/vscode/User/settings.json" "$HOME/Library/Application Support/Code/User/settings.json"
ln -sf "$HOME/.config/vscode/User/keybindings.json" "$HOME/Library/Application Support/Code/User/keybindings.json"

cat $HOME/.config/vscode/extensions | xargs -L 1 code --install-extension
