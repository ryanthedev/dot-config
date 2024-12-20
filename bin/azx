#!/bin/zsh

# Check if fzf is installed
if ! command -v fzf >/dev/null 2>&1; then
    echo "Error: fzf is not installed. Please install it first."
    exit 1
fi

# Check if Azure CLI is installed
if ! command -v az >/dev/null 2>&1; then
    echo "Error: Azure CLI is not installed. Please install it first."
    exit 1
fi

# Check if logged in to Azure
if ! az account show >/dev/null 2>&1; then
    echo "Error: Not logged in to Azure. Please run 'az login' first."
    exit 1
fi

# Get current subscription
current_subscription=$(az account show --query name -o tsv)

# List all subscriptions and use fzf to select one
selected_subscription=$(az account list \
    --query '[].{name:name}' \
    -o tsv \
    | fzf --height 40% \
        --prompt="Current subscription: $current_subscription > " \
        --header="Select Azure Subscription" \
        --preview 'az account show --subscription {} --query "{Name:name, ID:id, TenantID:tenantId}" -o yaml')

# Check if a subscription was selected
if [ -n "$selected_subscription" ]; then
    # Set the subscription
    az account set --subscription "$selected_subscription"
    echo "Switched to subscription: $selected_subscription"
else
    echo "No subscription selected. Keeping current subscription: $current_subscription"
fi
