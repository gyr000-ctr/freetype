test_env = ['FREETYPE_TESTS_DATA_DIR='
            + join_paths(meson.current_source_dir(), 'data')]

###

test_issue_1063 = executable('issue-1063',
  files([ 'issue-1063/main.c' ]),
  dependencies: freetype_dep,
)

test('issue-1063',
  test_issue_1063,
  env: test_env,
  suite: 'regression')

###

varc_hvvar_fonts = custom_target('varc-hvvar-fonts',
  input: files('data/varc-static-gvar.ttf'),
  output: ['varc-static-hvar.ttf', 'varc-static-vvar.ttf'],
  command: [python_exe, files('varc/make-hvvar-fonts.py'), '@INPUT@', '@OUTPUT@'],
)

test_varc = executable('varc',
  files([ 'varc/main.c' ]),
  dependencies: freetype_dep,
)

test('varc',
  test_varc,
  env: test_env,
  depends: varc_hvvar_fonts,
  args: [varc_hvvar_fonts[0], varc_hvvar_fonts[1]],
  suite: 'regression')

###

test_outline_reverse = executable('outline-reverse',
  files([ 'outline-reverse/main.c' ]),
  dependencies: freetype_dep,
)

test('outline-reverse',
  test_outline_reverse,
  suite: 'regression')

###

issue_1469_fonts = custom_target('issue-1469-fonts',
  output: [
    'issue-1469-32764.ttf',
    'issue-1469-32765.ttf',
    'issue-1469-32766.ttf',
    'issue-1469-32767.ttf',
  ],
  command: [python_exe, files('issue-1469/make-fonts.py'), '@OUTPUT@'],
  build_by_default: true,
)

test_issue_1469 = executable('issue-1469',
  files('issue-1469/main.c'),
  dependencies: freetype_dep,
)

test('issue-1469',
  test_issue_1469,
  depends: issue_1469_fonts,
  args: [issue_1469_fonts[0], issue_1469_fonts[1],
         issue_1469_fonts[2], issue_1469_fonts[3]],
  suite: 'regression',
  # The signed-short boundary requires four ~32767-component fixtures.
  timeout: 180,
)

###

kern2_fonts = custom_target('kern2-fonts',
  output: [
    'kern2-add.ttf',
    'kern2-override.ttf',
    'kern2-mixed.ttf',
    'kern0-only.ttf',
    'kern2-truncated.ttf',
    'kern2-oob-index.ttf',
    'kern2-stream.ttf',
  ],
  command: [python_exe, files('kern2/make-fonts.py'), '@OUTPUT@'],
)

test_kern2 = executable('kern2',
  files([ 'kern2/main.c' ]),
  dependencies: freetype_dep,
  # The failure-code checks drive the sfnt loader through internal headers.
  include_directories: include_directories('../src'),
)

test('kern2',
  test_kern2,
  env: test_env,
  depends: kern2_fonts,
  args: [
    kern2_fonts[0], kern2_fonts[1], kern2_fonts[2],
    kern2_fonts[3], kern2_fonts[4], kern2_fonts[5],
    kern2_fonts[6],
  ],
  suite: 'regression',
  timeout: 30,
)

###

if harfbuzz_opt == 'YES' or harfbuzz_opt == 'dynamic'
  issue_1441_c_args = []
  if harfbuzz_opt == 'dynamic'
    issue_1441_c_args += ['-DTEST_DYNAMIC_HARFBUZZ']
  endif

  issue_1441_fonts = custom_target('issue-1441-fonts',
    output: ['issue-1441-latin.ttf', 'issue-1441-mixed.ttf'],
    command: [python_exe, files('issue-1441/make-fonts.py'), '@OUTPUT@'],
  )

  test_issue_1441 = executable('issue-1441',
    files('issue-1441/main.c'),
    dependencies: freetype_dep,
    c_args: issue_1441_c_args,
  )

  test('issue-1441',
    test_issue_1441,
    depends: issue_1441_fonts,
    args: [issue_1441_fonts[0], issue_1441_fonts[1]],
    suite: 'regression',
  )
endif

# EOF
