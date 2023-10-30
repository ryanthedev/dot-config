#!/bin/bash
set +x

if [ "$1" = "-help" ]; then
    echo "Usage: $0 [u|d] [amount]"
    echo "  u      Increase mouse sensitivity."
    echo "  d      Decrease mouse sensitivity."
    echo "  amount (optional) The amount by which to adjust sensitivity (default: 0.3)."
    exit 0
fi

# Get the current Coordinate Transformation Matrix values
current_matrix=($(xinput list-props 8 | grep "Coordinate Transformation Matrix" | awk '{gsub(",", "", $5); gsub(",", "", $6); gsub(",", "", $7); gsub(",", "", $8); gsub(",", "", $9); gsub(",", "", $10); gsub(",", "", $11); gsub(",", "", $12); print $5, $6, $7, $8, $9, $10, $11, $12}'))

if [ "$1" = "u" ]; then
    operation="+"
elif [ "$1" = "d" ]; then
    operation="-"
else
    echo "Invalid operation. Use 'u' to increase or 'd' to decrease sensitivity."
    exit 1
#!/bin/bash
set +x

if [ "$1" = "-help" ]; then
    echo "Usage: $0 [u|d] [amount]"
    echo "  u      Increase mouse sensitivity."
    echo "  d      Decrease mouse sensitivity."
    echo "  amount (optional) The amount by which to adjust sensitivity (default: 0.3)."
    exit 0
fi

# Get the current Coordinate Transformation Matrix values
current_matrix=($(xinput list-props 8 | grep "Coordinate Transformation Matrix" | awk '{gsub(",", "", $5); gsub(",", "", $6); gsub(",", "", $7); gsub(",", "", $8); gsub(",", "", $9); gsub(",", "", $10); gsub(",", "", $11); gsub(",", "", $12); print $5, $6, $7, $8, $9, $10, $11, $12}'))

if [ "$1" = "u" ]; then
    operation="+"
elif [ "$1" = "d" ]; then
    operation="-"
else
    echo "Invalid operation. Use 'u' to increase or 'd' to decrease sensitivity."
    exit 1
fi

if [ -n "$2" ] && [ "$(echo "$2" | bc 2>/dev/null)" = "$2" ]; then
  amount=$2
else
  amount="0.3"
fi

current_matrix[0]=$(echo "${current_matrix[0]} ${operation} ${amount}" | bc)
current_matrix[4]=$(echo "${current_matrix[4]} ${operation} ${amount}" | bc)

matrix_str="${current_matrix[*]}"
xinput set-prop 8 'Coordinate Transformation Matrix' $matrix_str 1.000000
echo $matrix_str
fi

if [ -n "$2" ] && [ "$(echo "$2" | bc 2>/dev/null)" = "$2" ]; then
  amount=$2
else
  amount="0.3"
fi

current_matrix[0]=$(echo "${current_matrix[0]} ${operation} ${amount}" | bc)
current_matrix[4]=$(echo "${current_matrix[4]} ${operation} ${amount}" | bc)

matrix_str="${current_matrix[*]}"
xinput set-prop 8 'Coordinate Transformation Matrix' $matrix_str 1.000000
echo $matrix_str
