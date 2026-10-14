local on_lsp_attach = function(client, bufnr)
  local opts = { buffer = bufnr, remap = false }
  local telescope = require("telescope.builtin")
  vim.keymap.set("n", "go", function()
    telescope.lsp_type_definitions()
  end, opts)
  vim.keymap.set("n", "gR", function()
    telescope.lsp_references()
  end, opts)
  vim.keymap.set("n", "gi", function()
    telescope.lsp_implementations()
  end, opts)
  vim.keymap.set("n", "gd", function()
    vim.lsp.buf.definition()
  end, opts)
  vim.keymap.set("n", "ge", function()
    telescope.diagnostics()
  end, opts)
  vim.keymap.set("n", "<leader>vws", function()
    vim.lsp.buf.workspace_symbol()
  end, opts)
  vim.keymap.set("n", "gn", function()
    vim.diagnostic.goto_next()
  end, opts)
  vim.keymap.set("n", "gp", function()
    vim.diagnostic.goto_prev()
  end, opts)
  vim.keymap.set("n", "<leader>xca", function()
    vim.lsp.buf.code_action()
  end, opts)
  vim.keymap.set("n", "<leader>xrn", function()
    vim.lsp.buf.rename()
  end, opts)
end

return {
	{
		"Wansmer/symbol-usage.nvim",
		event = "LspAttach",
		config = function()
			require("symbol-usage").setup()
		end,
	},
	{
		"towolf/vim-helm",
		ft = "helm",
	},
	{
		"j-hui/fidget.nvim",
		-- LSP progress UI — nothing to render until a server attaches.
		event = "LspAttach",
		config = function()
			require("fidget").setup()
		end,
	},
	{
		"VonHeikemen/lsp-zero.nvim",
		branch = "v3.x",
		lazy = true,
		config = false,
		init = function()
			-- Disable automatic setup, we are doing it manually
			vim.g.lsp_zero_extend_cmp = 0
			vim.g.lsp_zero_extend_lspconfig = 0
		end,
	},
	{
		"williamboman/mason.nvim",
		lazy = false,
    opts = {
      registries = {
          "github:mason-org/mason-registry",
          "github:Crashdummyy/mason-registry",
      },
    },
    config = function(_, opts)
      require("mason").setup(opts)
      -- Deferred to VeryLazy: mason-registry pulls in its GitHub source module
      -- and hits the network, neither of which belongs on the startup path.
      -- Mason itself still loads eagerly so its bin/ is on PATH before any
      -- server (or conform's prettier) is resolved.
      vim.api.nvim_create_autocmd("User", {
        pattern = "VeryLazy",
        once = true,
        callback = function()
          local ensure = { "roslyn", "html-lsp", "prettier" }
          local mr = require("mason-registry")
          mr.refresh(function()
            for _, name in ipairs(ensure) do
              local ok, pkg = pcall(mr.get_package, name)
              if ok and not pkg:is_installed() then
                pkg:install()
              end
            end
          end)
        end,
      })
    end,
	},
	-- Autocompletion
	{
		"hrsh7th/nvim-cmp",
		event = { "InsertEnter", "CmdlineEnter" },
		dependencies = {
			{ "L3MON4D3/LuaSnip" },
			{ "hrsh7th/cmp-buffer" },
			{ "hrsh7th/cmp-path" },
			{ "hrsh7th/cmp-cmdline" },
			{ "hrsh7th/cmp-nvim-lsp-signature-help" },
			{ "saadparwaiz1/cmp_luasnip" },
		},
		config = function()
			-- Here is where you configure the autocompletion settings.
			local lsp_zero = require("lsp-zero")
			lsp_zero.extend_cmp()

			-- And you can configure cmp even more, if you want to.
			local cmp = require("cmp")
			local cmp_action = lsp_zero.cmp_action()

			cmp.setup({
				snippet = {
					expand = function(args)
						require("luasnip").lsp_expand(args.body)
					end,
				},
				sources = {
					{ name = "path" },
					{ name = "nvim_lsp" },
					{ name = "nvim_lua" },
					{ name = "luasnip" },
					{ name = "buffer" },
					{ name = "nvim_lsp_signature_help" },
          per_filetype = {
            codecompanion = { "codecompanion" },
          }
				},
				window = {
					completion = cmp.config.window.bordered(),
					documentation = cmp.config.window.bordered(),
				},
				formatting = lsp_zero.cmp_format(),
				mapping = cmp.mapping.preset.insert({
					["<Tab>"] = cmp_action.luasnip_supertab(),
					["<S-Tab>"] = cmp_action.luasnip_shift_supertab(),
					["<CR>"] = cmp.mapping.confirm({ select = true }),
					["<C-u>"] = cmp.mapping.scroll_docs(-4),
					["<C-d>"] = cmp.mapping.scroll_docs(4),
				}),
			})
			require("luasnip.loaders.from_vscode").load({ paths = { "~/.config/snippets" } })

			-- Cmdline ':' completion
			cmp.setup.cmdline(":", {
				mapping = cmp.mapping.preset.cmdline(),
				sources = cmp.config.sources({
					{ name = "path" },
				}, {
					{ name = "cmdline" },
				}),
			})

			-- Cmdline '/' and '?' search completion
			cmp.setup.cmdline({ "/", "?" }, {
				mapping = cmp.mapping.preset.cmdline(),
				sources = {
					{ name = "buffer" },
				},
			})
		end,
	},
	-- LSP
	{
		"neovim/nvim-lspconfig",
		cmd = { "LspInfo", "LspInstall", "LspStart" },
		event = { "BufReadPre", "BufNewFile" },
		cond = function() return not vim.g.scrollback end,
		dependencies = {
			{ "hrsh7th/cmp-nvim-lsp" },
			{ "williamboman/mason-lspconfig.nvim" },
			{ "b0o/SchemaStore.nvim" },
		},
		config = function()
			-- Keymaps are bound from an LspAttach autocmd rather than a per-server
			-- on_attach: mason-lspconfig v2 starts servers via vim.lsp.enable(), so
			-- lspconfig's setup() hooks (and lsp-zero's on_attach) never fire for them.
			vim.api.nvim_create_autocmd("LspAttach", {
				callback = function(event)
					local client = vim.lsp.get_client_by_id(event.data.client_id)
					on_lsp_attach(client, event.buf)
				end,
			})

			local lsp_capabilities = vim.tbl_deep_extend(
				"force",
				require("cmp_nvim_lsp").default_capabilities(),
				{
					textDocument = {
						foldingRange = {
							dynamicRegistration = false,
							lineFoldingOnly = true,
						},
					},
				}
			)

			-- Applies to every server, including those auto-enabled by mason-lspconfig
			vim.lsp.config("*", { capabilities = lsp_capabilities })

			require("mason-lspconfig").setup({
				ensure_installed = { "vtsls", "eslint", "jsonls", "yamlls" },
			})

			vim.lsp.config("helm_ls", {
				settings = {
					["helm-ls"] = {
						yamlls = {
							path = "yaml-language-server",
						},
					},
				},
			})

			vim.lsp.config("vtsls", {
				settings = {
					typescript = {
						updateImportsOnFileMove = { enabled = "always" },
						suggest = { completeFunctionCalls = true },
						inlayHints = {
							parameterNames = { enabled = "literals" },
							parameterTypes = { enabled = true },
							variableTypes = { enabled = true },
							propertyDeclarationTypes = { enabled = true },
							functionLikeReturnTypes = { enabled = true },
						},
					},
					javascript = {
						updateImportsOnFileMove = { enabled = "always" },
						inlayHints = {
							parameterNames = { enabled = "literals" },
							variableTypes = { enabled = true },
						},
					},
				},
			})

			vim.lsp.config("jsonls", {
				settings = {
					json = {
						schemas = require("schemastore").json.schemas(),
						validate = { enable = true },
					},
				},
			})

			vim.lsp.config("yamlls", {
				settings = {
					yaml = {
						schemaStore = { enable = false, url = "" },
						schemas = require("schemastore").yaml.schemas(),
					},
				},
			})

			-- Swift: sourcekit-lsp (bundled with Xcode, not managed by Mason)
			vim.lsp.enable("sourcekit")
		end,
	},
	-- C# / Razor: Roslyn, the same language server VS Code's C# extension uses.
	-- Server comes from the Crashdummyy mason registry (package "roslyn").
	{
		"seblyng/roslyn.nvim",
		ft = { "cs", "razor" },
		init = function()
			-- Must be registered before the plugin loads: its plugin/roslyn.lua calls
			-- vim.lsp.enable("roslyn"), which starts the client immediately.
			-- Keymaps come from the shared LspAttach autocmd; inlay hints and code
			-- lens are switched on in after/plugin/autocommands.lua. Semantic tokens
			-- need nothing here: nvim 0.12 uses Roslyn's semanticTokens/range natively.
			vim.lsp.config("roslyn", {
				settings = {
					["csharp|inlay_hints"] = {
						csharp_enable_inlay_hints_for_implicit_object_creation = true,
						csharp_enable_inlay_hints_for_implicit_variable_types = true,
						csharp_enable_inlay_hints_for_lambda_parameter_types = true,
						csharp_enable_inlay_hints_for_types = true,
						dotnet_enable_inlay_hints_for_indexer_parameters = true,
						dotnet_enable_inlay_hints_for_literal_parameters = true,
						dotnet_enable_inlay_hints_for_object_creation_parameters = true,
						dotnet_enable_inlay_hints_for_other_parameters = true,
						dotnet_enable_inlay_hints_for_parameters = true,
						dotnet_suppress_inlay_hints_for_parameters_that_differ_only_by_suffix = true,
						dotnet_suppress_inlay_hints_for_parameters_that_match_argument_name = true,
						dotnet_suppress_inlay_hints_for_parameters_that_match_method_intent = true,
					},
					["csharp|code_lens"] = {
						-- Off: symbol-usage.nvim already shows usage counts for every LSP
						dotnet_enable_references_code_lens = false,
						dotnet_enable_tests_code_lens = true,
					},
					["csharp|completion"] = {
						dotnet_provide_regex_completions = true,
						dotnet_show_completion_items_from_unimported_namespaces = true,
						dotnet_show_name_completion_suggestions = true,
					},
					["csharp|background_analysis"] = {
						dotnet_analyzer_diagnostics_scope = "fullSolution",
						dotnet_compiler_diagnostics_scope = "fullSolution",
					},
					["csharp|symbol_search"] = {
						dotnet_search_reference_assemblies = true,
					},
					["csharp|quick_info"] = {
						dotnet_show_remarks_in_quick_info = true,
					},
					["csharp|highlighting"] = {
						dotnet_highlight_related_json_components = true,
						dotnet_highlight_related_regex_components = true,
					},
					["csharp|testing"] = {
						dotnet_use_semantic_test_discovery = true,
					},
					["csharp|auto_insert"] = {
						dotnet_enable_auto_insert = true,
					},
					["csharp|formatting"] = {
						dotnet_organize_imports_on_format = true,
					},
					navigation = {
						dotnet_navigate_to_decompiled_sources = true,
					},
				},
			})

			-- Roslyn's semantic token legend goes well past the LSP standard types,
			-- and colorschemes rarely define @lsp.type.* for the extras, so those
			-- tokens silently fall back to treesitter. Link them to treesitter
			-- captures; `default` lets a colorscheme that does define them win.
			local roslyn_token_links = {
				recordClass = "@lsp.type.class",
				recordStruct = "@lsp.type.struct",
				delegate = "@type",
				field = "@variable.member",
				constant = "@constant",
				extensionMethod = "@function.method",
				controlKeyword = "@keyword.conditional",
				operatorOverloaded = "@operator",
				label = "@label",
				excludedCode = "Comment",
				stringEscapeCharacter = "@string.escape",
				stringVerbatim = "@string",
				regexText = "@string.regexp",
				regexComment = "@comment",
				regexCharacterClass = "@constant.character",
				regexAnchor = "@operator",
				regexQuantifier = "@operator",
				regexAlternation = "@operator",
				regexGrouping = "@punctuation.bracket",
				regexOtherEscape = "@string.escape",
				regexSelfEscapedCharacter = "@string.escape",
				jsonPropertyName = "@property",
				jsonString = "@string",
				jsonNumber = "@number",
				jsonKeyword = "@boolean",
				jsonComment = "@comment",
				jsonOperator = "@operator",
				jsonPunctuation = "@punctuation.delimiter",
				xmlDocCommentName = "@tag",
				xmlDocCommentAttributeName = "@tag.attribute",
				xmlDocCommentAttributeQuotes = "@string",
				xmlDocCommentAttributeValue = "@string",
				xmlDocCommentDelimiter = "@tag.delimiter",
				xmlDocCommentEntityReference = "@character.special",
				xmlDocCommentText = "@comment.documentation",
				xmlDocCommentComment = "@comment",
				xmlDocCommentCDataSection = "@comment",
			}
			local function link_roslyn_tokens()
				for token, target in pairs(roslyn_token_links) do
					vim.api.nvim_set_hl(0, "@lsp.type." .. token, { link = target, default = true })
				end
			end
			link_roslyn_tokens()
			-- :colorscheme runs `hi clear`, which wipes these links
			vim.api.nvim_create_autocmd("ColorScheme", { callback = link_roslyn_tokens })
		end,
		opts = {},
	},
}
