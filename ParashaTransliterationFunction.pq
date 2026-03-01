let
    SourceMap = ParashaMap,
    TransliterateAshkenazi = (inputText as nullable text) as nullable text =>
        if inputText = null then null
        else
            List.Accumulate(
                SourceMap,
                inputText,
                (state, current) => Text.Replace(state, current{0}, current{1})
            )
in
    TransliterateAshkenazi
